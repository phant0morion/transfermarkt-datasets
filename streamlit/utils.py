from cProfile import label
from typing import List
import streamlit as st
import os
from pathlib import Path
import pandas as pd
from inflection import dasherize, titleize
from datetime import datetime, timedelta
import base64
import sys
import subprocess
from transfermarkt_datasets.core.dataset import Dataset
from transfermarkt_datasets.core.asset import Asset

MAX_OUTPUT_LINES = 50
MAX_LINE_LENGTH = 200

def truncate_output(output: str, max_lines: int, max_line_len: int) -> str:
    if not output:
        return ""
    lines = output.splitlines()
    truncated_lines = []
    for i, line in enumerate(lines):
        if i >= max_lines:
            truncated_lines.append(f"... (truncated - too many lines, total {len(lines)})")
            break
        if len(line) > max_line_len:
            truncated_lines.append(line[:max_line_len] + f"... (truncated - line too long, original length {len(line)})")
        else:
            truncated_lines.append(line)
    return "\\n".join(truncated_lines)

@st.cache_data
def load_td() -> Dataset:
    """Instantiate and initialise a Dataset, so it can be used in the app.

    Returns:
        Dataset: A transfermark_datasets.core.Dataset that is initialised and ready to be used.
    """
    st.write(f"DEBUG: os.getenv('STREAMLIT'): {os.getenv('STREAMLIT')}")
    st.write(f"DEBUG: os.getenv('STREAMLIT_SERVER_MODE'): {os.getenv('STREAMLIT_SERVER_MODE')}")

    # Temporarily bypass the condition to force DVC pull for debugging
    # if os.getenv("STREAMLIT") == "cloud":
    st.write("DEBUG: Attempting DVC pull (condition temporarily bypassed for debugging)")
    st.write("Running on Streamlit Cloud (or equivalent forced mode), attempting to pull data with DVC...")
    try:
        cmd = ["dvc", "pull", "data/prep", "-v"]
        st.write(f"Executing: {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        dvc_stdout_display = truncate_output(result.stdout, MAX_OUTPUT_LINES, MAX_LINE_LENGTH)
        dvc_stderr_display = truncate_output(result.stderr, MAX_OUTPUT_LINES, MAX_LINE_LENGTH)

        st.write(f"DVC pull stdout:\\n```\\n{dvc_stdout_display}\\n```")
        st.write(f"DVC pull stderr:\\n```\\n{dvc_stderr_display}\\n```")

        if result.returncode != 0:
            st.error(f"DVC pull failed with return code {result.returncode}.")
        else:
            st.success("DVC pull completed successfully.")

        st.write("Checking contents of 'data/' and 'data/prep/' directories...")
        try:
            # Debug: Print output of ls -l data/
            ls_data_cmd = ["ls", "-l", "data/"]
            st.write(f"Executing: {' '.join(ls_data_cmd)}")
            ls_data_result = subprocess.run(ls_data_cmd, capture_output=True, text=True, cwd="/workspaces/transfermarkt-datasets")
            
            ls_data_stdout_display = truncate_output(ls_data_result.stdout, 20, MAX_LINE_LENGTH)
            ls_data_stderr_display = truncate_output(ls_data_result.stderr, 20, MAX_LINE_LENGTH)
            st.write(f"Contents of 'data/' directory (after DVC attempt):\\n```\\n$ {' '.join(ls_data_cmd)}\\n{ls_data_stdout_display}\\n{ls_data_stderr_display}\\n```")

            # Debug: Print output of ls -l data/prep
            ls_prep_cmd = ["ls", "-l", "data/prep/"]
            # Ensure cwd is specified for this call as well
            ls_prep_result = subprocess.run(ls_prep_cmd, capture_output=True, text=True, cwd="/workspaces/transfermarkt-datasets")
            
            ls_prep_stdout_display = truncate_output(ls_prep_result.stdout, 20, MAX_LINE_LENGTH)
            ls_prep_stderr_display = truncate_output(ls_prep_result.stderr, 20, MAX_LINE_LENGTH)
            st.write(f"Contents of 'data/prep/' directory (after DVC attempt):\\n```\\n$ {' '.join(ls_prep_cmd)}\\n{ls_prep_stdout_display}\\n{ls_prep_stderr_display}\\n```")
        except Exception as e_ls:
            st.warning(f"Could not list directory contents: {e_ls}")

    except FileNotFoundError:
        st.error("DVC command not found. Ensure DVC is installed in the Streamlit Cloud environment and added to your project's dependencies (e.g., pyproject.toml).")
    except Exception as e:
        st.error(f"An error occurred during DVC pull setup or execution: {e}")
        print(f"Error during DVC pull: {e}") # Also print to server logs
    # else: # Corresponds to the temporarily bypassed if
    #     st.write("DEBUG: Not on Streamlit Cloud (or condition not met), skipping DVC pull.")

    # Determine the project root directory, assuming utils.py is in streamlit/
    # and the project root is one level up from the directory containing utils.py.
    project_root = Path(__file__).parent.parent.resolve()
    st.write(f"DEBUG: Determined project_root for Dataset: {project_root}")

    td = Dataset(base_path=project_root)
    td.load_assets()

    return td

def read_file_contents(file_path: str):
    """Read a markdown file in disk as a string.

    Args:
        markdown_file (str): The path of the file to be read.

    Returns:
        str: The contents of the file as a string.
    """
    return Path(file_path).read_text()

def draw_dataset_index(td: Dataset) -> None:

    md_index_lines = []

    for asset_name, asset in td.assets.items():
        if asset.public:
            titelized_asset_name = titleize(asset.frictionless_resource_name).lower()
            asset_anchor = dasherize(asset.frictionless_resource_name).lower()
            md_index_line = f"* [{titelized_asset_name}](#{asset_anchor})"
            md_index_lines.append(
                md_index_line
            )

    st.sidebar.markdown(
        "\n".join(md_index_lines)
    )

def draw_asset(asset: Asset) -> None:
    """Draw a transfermarkt-dataset asset summary

    Args:
        asset_name (str): Name of the asset
    """

    left_col, right_col = st.columns([5,1])

    title = titleize(asset.frictionless_resource_name).lower()
    left_col.subheader(title)

    left_col.markdown(asset.description)
    delta = get_records_delta(asset)
    right_col.metric(
        label="# of records",
        value=len(asset.prep_df),
        delta=delta,
        help="Total number of records in the asset / New records in the past week"
    )

    with st.expander("Attributes"):
        draw_asset_schema(asset)

    with st.expander("Explore"):
        draw_asset_explore(asset)

    st.markdown("---")

def draw_asset_explore(asset: Asset) -> None:
    """Draw dataframe together with dynamic filters for exploration.

    Args:
        asset (Asset): The asset to draw the explore for.
    """
    
    tagged_columns = [
        field.name
        for field in asset.schema.get_fields_by_tag("explore")
    ]
    default_columns = list(asset.prep_df.columns[:4].values)

    if len(tagged_columns) > 0:
        columns = tagged_columns
    else:
        columns = default_columns

    filter_columns = st.multiselect(
        label="Search by",
        options=asset.prep_df.columns,
        default=columns
    )
    if len(filter_columns) == 0:
        filter_columns = columns

    st_cols = st.columns(len(filter_columns))

    df = asset.prep_df.copy()

    for st_col, at_col in zip(st_cols, filter_columns):

        options = list(df[at_col].unique())
 
        selected = st_col.selectbox(
            label=at_col,
            options=options,
            key=(asset.name + "-" + at_col)
        )
        if selected:
            df = df[df[at_col] == selected]

    MAX_DF_LENGTH = 20

    df_length = len(df)
    if df_length > MAX_DF_LENGTH:
        st.dataframe(
            df.head(MAX_DF_LENGTH)
        )
        st.warning(f"""
        The dataframe size ({df_length}) exceeded the maximum and has been truncated. 
        """)

    else:
        st.dataframe(df)


def draw_asset_schema(asset: Asset) -> None:
    st.dataframe(
        asset.schema_as_dataframe().astype(str),
        use_container_width=True
    )

# https://gist.github.com/treuille/8b9cbfec270f7cda44c5fc398361b3b1#file-render_svg-py-L12
def render_svg(svg, caption):
    """Renders the given svg string."""
    b64 = base64.b64encode(svg.encode('utf-8')).decode("utf-8")
    html_style = """
    <style>
        figure {
            border: 1px #cccccc solid;
            padding: 4px;
            margin: auto;
        }
        figcaption {
            background-color: black;
            color: white;
            font-style: italic;
            padding: 2px;
            text-align: center;
        }
    </style>
    """
    html_image = r'<img src="data:image/svg+xml;base64,%s"/>' % b64
    html_caption = f"<figcaption>{caption}</figcaption>"
    html_figure = f"""
    {html_style}
    <figure>
    {html_image}
    {html_caption}
    </figure>
    
    &nbsp;
    """
    st.write(html_figure, unsafe_allow_html=True)

def draw_dataset_er_diagram(image, caption) -> None:
    with open(image) as image:
        svg_string = "".join(image.readlines())

    render_svg(svg_string, caption)

def get_records_delta(asset: Asset, offset: int = 7) -> int:
    """Get an asset records' delta (number of new records in last n days).

    Args:
        asset (Asset): The asset to be calculating the delta from.
        offset (int, optional): Number in days to be consider for the delta calculation. Defaults to 7.

    Returns:
        int: Number of records.
    """
    df = asset.prep_df

    if "date" in df.columns:
        dt = pd.to_datetime(df["date"])
        delta = len(df[dt > (datetime.now() - timedelta(days=offset))])
        return delta
    else:
        return None
