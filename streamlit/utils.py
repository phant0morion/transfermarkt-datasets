from typing import List, Optional, Union
import streamlit as st
import os
import subprocess
from pathlib import Path
from io import StringIO

from transfermarkt_datasets.core.dataset import Dataset
from transfermarkt_datasets.core.asset import Asset

# --- Constants ---
CACHE_TTL_SECONDS = 60 * 60 * 24  # 24 hours


# --- Utility Functions ---

@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_project_root() -> Path:
    """
    Determines the project root directory for both local and Streamlit Cloud environments.
    """
    # Check if running in Streamlit Cloud environment
    if os.getenv("STREAMLIT_SERVER_MODE") == "cloud" or os.path.exists("/mount/src"):
        # In Streamlit Cloud, try common mount points
        potential_paths = [
            Path("/mount/src/transfermarkt-datasets"),
            Path("/mount/src"),
        ]
        
        for path in potential_paths:
            if path.exists() and (path / "data").exists():
                return path.resolve()
        
        # Fallback - just use the first existing path
        for path in potential_paths:
            if path.exists():
                return path.resolve()
                
        return Path("/mount/src").resolve()
    
    else:
        # Local environment - use the location of this script as reference
        current_file_path = Path(__file__).resolve()
        # Navigate up from streamlit/utils.py to project root
        project_root = current_file_path.parent.parent
        
        # Verify we found the right directory
        if (project_root / "data").exists():
            return project_root.resolve()
            
        # Last resort - assume current working directory
        return Path.cwd().resolve()


def run_dvc_pull(project_root: Path) -> bool:
    """
    Run DVC pull command to download data files.
    Returns True if successful, False otherwise.
    """
    try:
        result = subprocess.run(
            ["dvc", "pull", "data/prep"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0:
            st.success("✅ Data files downloaded successfully")
            return True
        else:
            st.warning(f"⚠️ DVC pull completed with warnings (exit code: {result.returncode})")
            if result.stderr:
                st.text(f"Details: {result.stderr[:500]}")
            return True  # DVC often returns non-zero even on success
            
    except subprocess.TimeoutExpired:
        st.error("❌ DVC pull timed out after 5 minutes")
        return False
    except FileNotFoundError:
        st.warning("⚠️ DVC not found - assuming data files are already present")
        return True
    except Exception as e:
        st.warning(f"⚠️ DVC pull encountered an issue: {str(e)}")
        return True  # Continue anyway - data might already be present


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def check_and_pull_data():
    """Check if data files exist and pull them if needed."""
    # Quick check first - if critical files exist, return immediately
    project_root = get_project_root()
    prep_path = project_root / "data" / "prep"
    critical_files = [
        prep_path / "games.csv.gz",
        prep_path / "clubs.csv.gz"
    ]
    
    # Fast path - if files exist, don't do anything
    missing_files = [f for f in critical_files if not f.exists()]
    if not missing_files:
        return True
    
    # If files are missing, check if we're in cloud and pull them
    is_cloud = (
        os.getenv("STREAMLIT_SERVER_MODE") == "cloud" or 
        os.path.exists("/mount/src") or
        os.getenv("STREAMLIT") == "cloud"
    )
    
    if is_cloud:
        st.info("📥 Downloading data files...")
        success = run_dvc_pull(project_root)
        if not success:
            st.error("❌ Failed to download data files")
            return False
    else:
        st.error("❌ Data files not found. Please run `dvc pull data/prep` to download them.")
        return False
    
    # Verify files exist after potential pull
    still_missing = [f for f in critical_files if not f.exists()]
    if still_missing:
        st.error(f"❌ Critical data files still missing: {[f.name for f in still_missing]}")
        return False
    
    st.success("✅ All data files are available")
    return True

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Loading dataset...")
def load_td():
    """Load the dataset with proper error handling for both local and cloud environments."""
    
    project_root = get_project_root()
    config_file_path = str(project_root / "config.yml")
    
    # Ensure data files are available
    if not check_and_pull_data():
        st.error("❌ Data files not available")
        st.stop()

    try:
        # Initialize Dataset with proper paths
        td = Dataset(
            base_path=str(project_root), 
            config_file=config_file_path,
            assets_root=str(project_root),
            assets_relative_path="transfermarkt_datasets/assets"
        )
        
        # DO NOT load assets immediately - this causes memory issues
        # Assets will be loaded on-demand when user requests data
        # td.load_assets()  # REMOVED: This was loading all CSV files into memory
        
        # Verify key assets are available (just check they exist in the registry)
        if not td.assets:
            st.error("❌ No assets found in the dataset")
            st.stop()
            
        return td
        
    except FileNotFoundError as e:
        missing_file = getattr(e, 'filename', str(e))
        # Check if we're running in Streamlit context
        try:
            from streamlit.runtime import get_instance
            if get_instance() is not None:
                st.error(f"❌ Required file not found: {missing_file}")
                st.stop()
            else:
                raise RuntimeError(f"Required file not found: {missing_file}")
        except:
            raise RuntimeError(f"Required file not found: {missing_file}")
        # Check if we're running in Streamlit context
        try:
            from streamlit.runtime import get_instance
            if get_instance() is not None:
                st.info("Please ensure all required files are present in the repository.")
                st.stop()
            else:
                raise RuntimeError("Please ensure all required files are present in the repository.")
        except:
            raise RuntimeError("Please ensure all required files are present in the repository.")
        
    except Exception as e:
        # Check if we're running in Streamlit context
        try:
            from streamlit.runtime import get_instance
            if get_instance() is not None:
                st.error(f"❌ Failed to initialize dataset: {str(e)}")
                st.stop()
            else:
                raise RuntimeError(f"Failed to initialize dataset: {str(e)}")
        except:
            raise RuntimeError(f"Failed to initialize dataset: {str(e)}")

def load_club_data(_dataset: Optional[str] = None):
    """Load club data from CSV files."""
    try:
        project_root = get_project_root()
        clubs_path = project_root / "data" / "prep" / "clubs.csv.gz"
        
        if not clubs_path.exists():
            st.error(f"❌ Club data file not found: {clubs_path}")
            return None
            
        import pandas as pd
        clubs_df = pd.read_csv(clubs_path)
        return clubs_df
        
    except Exception as e:
        st.error(f"❌ Failed to load club data: {str(e)}")
        return None
