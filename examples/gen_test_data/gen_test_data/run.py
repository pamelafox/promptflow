import json
import os
from datetime import datetime
from pathlib import Path

import configargparse

from promptflow import PFClient
from promptflow._utils.logger_utils import get_logger
from promptflow.entities import Run

CONFIG_FILE = (Path(__file__).parents[1] / "config.ini").resolve()

# in order to import from absoluate path, which is required by mldesigner
os.sys.path.insert(0, os.path.abspath(Path(__file__).parent))

from common import clean_data_and_save, split_document, count_non_blank_lines  # noqa: E402
from constants import TEXT_CHUNK  # noqa: E402

logger = get_logger("data.gen")


def batch_run_flow(
    pf: PFClient,
    flow_folder: str,
    flow_input_data: str,
    flow_batch_run_size: int,
):
    logger.info("Step 2: Start to batch run 'generate_test_data_flow'...")
    base_run = pf.run(
        flow=flow_folder,
        data=flow_input_data,
        stream=True,
        environment_variables={
            "PF_WORKER_COUNT": str(flow_batch_run_size),
            "PF_BATCH_METHOD": "spawn",
        },
        column_mapping={TEXT_CHUNK: "${data.text_chunk}"},
        debug=True,
    )
    logger.info("Batch run is completed.")
    return base_run


def get_batch_run_output(pf: PFClient, base_run: Run):
    logger.info(f"Start to get batch run {base_run.name} details.")
    details = pf.get_details(base_run, all_results=True)
    question = details["outputs.question"].tolist()
    suggested_answer = details["outputs.suggested_answer"].tolist()
    debug_info = details["outputs.debug_info"].tolist()
    return [
        {"question": q, "suggested_answer": g, "debug_info": d}
        for q, g, d in zip(question, suggested_answer, debug_info)
    ]


def run_local(
    documents_folder,
    document_chunk_size,
    document_nodes_file,
    flow_folder,
    flow_batch_run_size,
    output_folder,
    should_skip_split,
):
    text_chunks_path = document_nodes_file
    inner_folder = os.path.join(output_folder, datetime.now().strftime("%b-%d-%Y-%H-%M-%S"))
    if not os.path.isdir(inner_folder):
        os.makedirs(inner_folder)

    if not should_skip_split:
        text_chunks_path = split_document(document_chunk_size, documents_folder, inner_folder)

    pf = PFClient()
    batch_run = batch_run_flow(
        pf,
        flow_folder,
        text_chunks_path,
        flow_batch_run_size,
    )

    test_data_set = get_batch_run_output(pf, batch_run)

    # Store intermedian batch run output results
    jsonl_str = "\n".join(map(json.dumps, test_data_set))
    intermedian_batch_run_res = os.path.join(inner_folder, "batch-run-result.jsonl")
    with open(intermedian_batch_run_res, "wt") as text_file:
        print(f"{jsonl_str}", file=text_file)

    clean_data_output = os.path.join(inner_folder, "test-data.jsonl")
    clean_data_and_save(test_data_set, clean_data_output)


def run_cloud(
    documents_folder,
    document_chunk_size,
    document_nodes_file,
    flow_folder,
    subscription_id,
    resource_group,
    workspace_name,
    aml_cluster,
    prs_instance_count,
    prs_mini_batch_size,
    prs_max_concurrency_per_instance,
    should_skip_split,
):
    # lazy import azure dependencies
    try:
        from azure.ai.ml import Input as V2Input, MLClient, dsl, load_component
        from azure.identity import DefaultAzureCredential
        from constants import ENVIRONMENT_DICT_FIXED_VERSION
    except ImportError:
        raise ImportError(
            "Please install azure dependencies using the following command: "
            + "`pip install -r requirements_cloud.txt`"
        )

    @dsl.pipeline(
        non_pipeline_inputs=[
            "flow_yml_path",
            "should_skip_doc_split",
            "instance_count",
            "mini_batch_size",
            "max_concurrency_per_instance",
        ]
    )
    def gen_test_data_pipeline(
        data_input: V2Input,
        flow_yml_path: str,
        should_skip_doc_split: bool,
        chunk_size=1024,
        instance_count=1,
        mini_batch_size=1,
        max_concurrency_per_instance=2,
    ):
        from components import split_document_component, clean_data_and_save_component
        data = (
            data_input
            if should_skip_doc_split
            else split_document_component(documents_folder=data_input, chunk_size=chunk_size).outputs.document_node_output
        )
        flow_node = load_component(flow_yml_path)(
            data=data,
            text_chunk="${data.text_chunk}",
            # connections={
            #     key: {"connection": value["connection"].format(connection_name=connection_name)}
            #     for key, value in CONNECTIONS_TEMPLATE.items()
            # },
        )
        flow_node.mini_batch_size = mini_batch_size
        flow_node.max_concurrency_per_instance = max_concurrency_per_instance
        flow_node.set_resources(instance_count=instance_count)
        # flow_node.allowed_failed_count = -1
        # Should use `mount` mode to ensure PRS complete merge output lines.
        flow_node.outputs.flow_outputs.mode = "mount"
        clean_data_and_save_component(test_data_set_folder=flow_node.outputs.flow_outputs).outputs.test_data_output

    def get_ml_client(subscription_id: str, resource_group: str, workspace_name: str):
        credential = DefaultAzureCredential(exclude_shared_token_cache_credential=True)
        return MLClient(
            credential=credential,
            subscription_id=subscription_id,
            resource_group_name=resource_group,
            workspace_name=workspace_name,
        )

    ml_client = get_ml_client(subscription_id, resource_group, workspace_name)

    if should_skip_split:
        data_input = V2Input(path=document_nodes_file, type="uri_file")
    else:
        data_input = V2Input(path=documents_folder, type="uri_folder")

    prs_configs = {
        "instance_count": prs_instance_count,
        "mini_batch_size": prs_mini_batch_size,
        "max_concurrency_per_instance": prs_max_concurrency_per_instance,
    }

    pipeline_with_flow = gen_test_data_pipeline(
        data_input=data_input,
        flow_yml_path=os.path.join(flow_folder, "flow.dag.yaml"),
        should_skip_doc_split=should_skip_split,
        chunk_size=document_chunk_size,
        **prs_configs,
    )
    pipeline_with_flow.compute = aml_cluster
    studio_url = ml_client.jobs.create_or_update(pipeline_with_flow).studio_url
    logger.info(f"Completed to submit pipeline. Experiment Link: {studio_url}")


if __name__ == "__main__":
    if Path(CONFIG_FILE).is_file():
        parser = configargparse.ArgParser(default_config_files=[CONFIG_FILE])
    else:
        raise Exception(
            f"'{CONFIG_FILE}' does not exist. "
            + "Please check if you are under the wrong directory or the file is missing."
        )

    parser.add_argument("--cloud", action="store_true", help="cloud flag")
    parser.add_argument("--documents_folder", type=str, help="Documents folder path")
    parser.add_argument("--document_chunk_size", type=int, help="Document chunk size, default is 1024")
    parser.add_argument(
        "--document_nodes_file", type=str, help="Document nodes file, default is ./document_nodes.jsonl"
    )

    parser.add_argument("--flow_folder", required=True, type=str, help="Test data generation flow folder path")
    parser.add_argument(
        "--flow_batch_run_size",
        type=int,
        help="Test data generation flow batch run size, default is 16",
    )
    # Configs for local
    parser.add_argument("--output_folder", type=str, help="Output folder path.")
    # Configs for cloud
    parser.add_argument("--subscription_id", help="AzureML workspace subscription id")
    parser.add_argument("--resource_group", help="AzureML workspace resource group name")
    parser.add_argument("--workspace_name", help="AzureML workspace name")
    parser.add_argument("--aml_cluster", help="AzureML cluster name")
    parser.add_argument("--prs_instance_count", type=int, help="Parallel run step instance count")
    parser.add_argument("--prs_mini_batch_size", help="Parallel run step mini batch size")
    parser.add_argument(
        "--prs_max_concurrency_per_instance", type=int, help="Parallel run step max concurrency per instance"
    )
    args = parser.parse_args()

    should_skip_split_documents = False
    if args.document_nodes_file and Path(args.document_nodes_file).is_file():
        should_skip_split_documents = True
    elif not args.documents_folder or not Path(args.documents_folder).is_dir():
        parser.error("Either 'documents_folder' or 'document_nodes_file' should be specified correctly.")
    
    if args.cloud:
        logger.info("Start to generate test data at cloud...")
    else:
        logger.info("Start to generate test data at local...")
    
    if should_skip_split_documents:
        logger.info(f"Skip step 1 'Split documents to document nodes' as received document nodes from input file '{args.document_nodes_file}'.")
        logger.info(f"Collected {count_non_blank_lines(args.document_nodes_file)} document nodes.")

    if args.cloud:
        run_cloud(
            args.documents_folder,
            args.document_chunk_size,
            args.document_nodes_file,
            args.flow_folder,
            args.subscription_id,
            args.resource_group,
            args.workspace_name,
            args.aml_cluster,
            args.prs_instance_count,
            args.prs_mini_batch_size,
            args.prs_max_concurrency_per_instance,
            should_skip_split_documents,
        )
    else:
        run_local(
            args.documents_folder,
            args.document_chunk_size,
            args.document_nodes_file,
            args.flow_folder,
            args.flow_batch_run_size,
            args.output_folder,
            should_skip_split_documents,
        )