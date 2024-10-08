import json
import logging
import time
from glob import glob

import pandas as pd
from sqlalchemy import create_engine

from models import create_tables
from models.db import get_postgres_conn_string

logger = logging.getLogger(__name__)
logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)


def load_datasets_from_filesystem() -> dict[str, pd.DataFrame]:
    """
    This function loads the datasets from filesystem and preprocesses them.
    The function reads CSV files from the specified directory, assumes certain column names for consistency, and flattens 'annotator_metadata' into separate columns.
    It also converts 'annotator_metadata' values from JSON format to Pandas DataFrame and then normalizes it using json_normalize.
    Additionally, it checks if there are any CSV files in the specified directory, raising a ValueError if no datasets are found.
    """
    file_list = glob("resources/datasets/validation/*_all.csv")
    dataset_headers = [
        "task_id",
        "question",
        "level",
        "answer",
        "file_name",
        "file_path",
        "annotator_metadata",
    ]
    if len(file_list) == 0:
        raise ValueError("There are no datasets available in the resources path")

    cleaned_datasets = {}
    for file in file_list:
        dataset_df = pd.read_csv(file, names=dataset_headers, header=0)
        # dataset_df["created_at"] = pd.Timestamp.now()
        # dataset_df["modified_at"] = pd.Timestamp.now()
        dataset_df["annotator_metadata"] = dataset_df["annotator_metadata"].apply(
            preprocess_annotator_metadata
        )

        # Flatten annotator_metadata fields
        json_struct = json.loads(dataset_df.to_json(orient="records"))
        flattened_dataset_df = pd.json_normalize(json_struct)
        flattened_dataset_df.columns = [
            col.replace("annotator_metadata.", "")
            for col in flattened_dataset_df.columns
        ]

        # Fill N/A
        flattened_dataset_df["metadata_num_tools"] = pd.to_numeric(
            flattened_dataset_df["metadata_num_tools"], errors="coerce"
        ).astype("Int64")

        # Update file paths from S3
        flattened_dataset_df["file_path"] = (
            "damg7374-a1-store/" + flattened_dataset_df["file_name"]
        )

        flattened_dataset_df.to_csv("resources/cleaned_datasets/1.csv", index=False)
        cleaned_datasets[file] = flattened_dataset_df

        print(flattened_dataset_df.columns)

    return cleaned_datasets


def preprocess_annotator_metadata(metadata: str) -> dict:
    logger.info("Fixing annotator metadata")
    metadata_json = fix_json_structure(metadata)
    return {
        "metadata_steps": metadata_json["Steps"],
        "metadata_num_steps": metadata_json["Number of steps"],
        "metadata_time_taken": metadata_json["How long did this take?"],
        "metadata_tools": metadata_json["Tools"],
        "metadata_num_tools": metadata_json["Number of tools"],
    }


def fix_json_structure(metadata: str) -> dict:
    """
    Fix improperly formatted JSON structure in the `Annotator Metadata` column. The double quotes, single quotes and
    english punctuation are not compliant with JSON standards
    :param metadata:
    :return:
    """
    try:
        return json.loads(
            metadata.replace('"', "TMP1").replace("'", '"').replace("TMP1", "'")
        )
    except json.JSONDecodeError:
        return json.loads(
            metadata.replace("'s", "TMP1")
            .replace("'t", "TMP2")
            .replace("'(", "TMP3")
            .replace('"', "'")
            .replace("'", '"')
            .replace("TMP2", "'t")
            .replace("TMP1", "'s")
            .replace("TMP3", "'(")
        )


def transfer_attachment(source_file_path: str) -> str:
    """
    Download the file attachments from Hugging Face dataset cache and upload to S3
    :param source_file_path:
    :return:
    """
    # TODO: Do last
    ...


def main():
    """
    Main function that loads datasets, sets up Postgres connection, creates tables if needed, and stores the cleaned data in the database.
    """
    dataframes = load_datasets_from_filesystem()

    # Setup Postgres connection
    postgres_conn_string = get_postgres_conn_string()
    engine = create_engine(postgres_conn_string)

    # Create tables if they don't already exist
    create_tables(engine)

    with engine.connect() as connection:
        for df_name, df in dataframes.items():
            start_time = time.time()
            df.to_sql(
                name="test_cases",
                con=connection,
                if_exists="append",
            )
            logger.info(
                f"Created table `test_cases` from {df_name} in {time.time_ns() - start_time} sec"
            )
    logger.info("Completed loading datasets to database")


if __name__ == "__main__":
    main()
