import streamlit as st
import os
import sys
import gc
import pandas as pd 
import duckdb 
from io import BytesIO
from datetime import datetime, date 
from pathlib import Path

# --- PAGE CONFIGURATION (MUST BE THE FIRST STREAMLIT COMMAND) ---
st.set_page_config(page_title="Transfermarkt Database", page_icon="⚽", layout="wide")

# Simple health check response
try:
    query_params = st.query_params if hasattr(st, 'query_params') else {}
    if query_params and any(check in str(query_params).lower() for check in ['health', 'check']):
        st.write("OK")
        st.stop()
except:
    pass

# --- Add parent directory to sys.path to find utils.py ---
try:
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.abspath(os.path.join(current_file_dir, '..'))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
except Exception as e_path:
    st.error(f"Error modifying sys.path: {e_path}")
    st.stop()

# --- IMPORT UTILITIES ---
try:
    from transfermarkt_datasets.core.asset import Asset 
    from transfermarkt_datasets.core.dataset import Dataset 
    from utils import load_td
except ImportError as e_import:
    st.error(f"Failed to import required modules: {e_import}")
    st.error("Please ensure you have installed all dependencies with: `pip install -r requirements.txt`")
    st.stop()
except Exception as e_gen_import:
    st.error(f"An unexpected error occurred during import: {e_gen_import}")
    st.stop()

# CRITICAL: Clean up old session state to prevent Streamlit Cloud caching issues
if "global_date_filter" in st.session_state:
    del st.session_state["global_date_filter"]

st.title("⚽ Transfermarkt Database 6 - FIXED")

st.markdown("""
Explore the Transfermarkt database, apply filters, and export the results to Excel.
""")

# Define Top 5 Leagues and their known competition codes
# These codes (e.g., 'GB1') should match 'competition_id' in your datasets
TOP_LEAGUES = {
    "Premier League (England)": "GB1",
    "La Liga (Spain)": "ES1",
    "Bundesliga (Germany)": "L1",
    "Serie A (Italy)": "IT1",
    "Ligue 1 (France)": "FR1",
}

# --- DYNAMIC PROJECT ROOT DETECTION ---
try:
    # Dynamically determine the project root (repo root)
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../'))
except Exception as e_proj_root:
    st.error(f"Error determining project root: {e_proj_root}")
    st.stop()

# Patch all data file path usage to use PROJECT_ROOT
# Patch for Asset.prep_path and all data file references
# (Assumes Asset.prep_path is relative to project root)

def get_asset_prep_path(asset_obj):
    # If path is already absolute, return as is
    if os.path.isabs(asset_obj.prep_path):
        return asset_obj.prep_path
    # Otherwise, join with PROJECT_ROOT
    return os.path.join(PROJECT_ROOT, asset_obj.prep_path)

# --- END DYNAMIC PROJECT ROOT DETECTION ---

# Load the dataset object (loads all assets)
@st.cache_data(ttl=1800, show_spinner=False, max_entries=1)
def get_dataset():
    """Load dataset with memory management and path flexibility"""
    try:
        gc.collect()  # Clean up before loading
        return load_td()
    except Exception as e:
        st.error(f"Failed to load dataset: {e}")
        return None

td = get_dataset()

# Add safety check for dataset loading
if td is None:
    st.error("❌ Failed to load dataset. Please check data files and try again.")
    st.stop()

# Verify essential assets are available
required_assets = ["cur_games", "cur_clubs", "cur_players"]
missing_assets = [asset for asset in required_assets if asset not in td.assets]

if missing_assets:
    st.error(f"❌ Missing required assets: {missing_assets}")
    st.info("Available assets: " + ", ".join(td.assets.keys()))
    st.stop()

# --- Enhanced Setup for Filters ---
# Load clubs data for team filtering - LAZY LOADING
@st.cache_data(ttl=1800, show_spinner=False, max_entries=1)
def load_club_data(_dataset):
    """Load club data with robust error handling - LAZY LOADING"""
    clubs_asset = _dataset.assets.get("cur_clubs")
    clubs_df_local = None
    club_id_to_name_local = {}
    club_name_to_id_local = {}
    available_club_names_local = []

    if clubs_asset:
        try:
            # LAZY LOADING: Only load clubs data when explicitly needed for filters
            # This prevents immediate memory usage on app startup
            clubs_asset.load_from_prep() 
            clubs_df_local = clubs_asset.prep_df
            if clubs_df_local is not None and 'club_id' in clubs_df_local.columns and 'name' in clubs_df_local.columns:
                available_club_names_local = sorted(clubs_df_local['name'].dropna().unique())
                temp_id_to_name = clubs_df_local.dropna(subset=['club_id', 'name']).set_index('club_id')['name'].to_dict()
                club_name_to_id_local = {
                    name: clubs_df_local[clubs_df_local['name'] == name]['club_id'].iloc[0] 
                    for name in available_club_names_local
                }
                club_id_to_name_local = {
                    club_id: name for name, club_id in club_name_to_id_local.items()
                }

        except FileNotFoundError as e_fnf_club:
            st.warning("⚠️ Club data file not found. Club filtering will be disabled.")
        except Exception as e_club:
            st.warning("⚠️ Could not load club data. Club filtering will be disabled.")
    return clubs_df_local, club_id_to_name_local, club_name_to_id_local, available_club_names_local

# LAZY LOADING: Only load clubs if user wants to use club filters
# Initialize with empty data initially to prevent immediate loading
clubs_df, club_id_to_name, club_name_to_id, available_club_names = None, {}, {}, []

# Check if user wants club filtering before loading club data
load_clubs_for_filtering = st.sidebar.checkbox("🏟️ Enable Club Filtering", 
    help="Check this to enable filtering by clubs. This will load additional data.")

if load_clubs_for_filtering:
    with st.spinner("Loading club data for filtering..."):
        clubs_df, club_id_to_name, club_name_to_id, available_club_names = load_club_data(td)

# --- End Enhanced Setup for Filters ---

# --- Function to get club names for selected leagues and seasons ---
@st.cache_data(ttl=1800, show_spinner=False, max_entries=10)
def get_club_names_for_leagues(
    _selected_league_codes: list, 
    _td_dataset: Dataset, # Use the specific type hint for td
    _club_id_to_name_map: dict,
    _start_year: int, 
    _end_year: int
):
    if not _selected_league_codes:
        return []

    games_asset = _td_dataset.assets.get("cur_games")
    if not games_asset:
        st.warning("Games asset ('cur_games') not found in dataset.")
        return []
    
    games_file_path = get_asset_prep_path(games_asset)
    if not os.path.exists(games_file_path):
        st.warning(f"Games data file not found: {games_file_path}")
        return []

    # Assuming season column is integer like 2022 for 2022/23 season
    season_conditions = f"CAST(season AS INTEGER) >= {_start_year} AND CAST(season AS INTEGER) <= {_end_year}"

    # Prepare league codes for SQL IN clause (ensure they are strings)
    league_codes_str = ", ".join([f"'{str(code)}'" for code in _selected_league_codes])

    query = f"""
    SELECT DISTINCT club_id
    FROM (
        SELECT home_club_id AS club_id FROM read_csv_auto('{str(games_file_path)}')
        WHERE competition_id IN ({league_codes_str}) AND {season_conditions}
        UNION ALL
        SELECT away_club_id AS club_id FROM read_csv_auto('{str(games_file_path)}')
        WHERE competition_id IN ({league_codes_str}) AND {season_conditions}
    ) AS combined_clubs
    WHERE club_id IS NOT NULL;
    """
    
    try:
        con = duckdb.connect(database=':memory:', read_only=False)
        club_ids_df = con.execute(query).fetchdf()
        con.close()

        if club_ids_df.empty:
            return []
        
        if not _club_id_to_name_map:
            return [] 

        club_names_found = []
        unique_club_ids_from_query = club_ids_df['club_id'].dropna().unique()

        for club_id_val in unique_club_ids_from_query: 
            if club_id_val in _club_id_to_name_map:
                club_names_found.append(_club_id_to_name_map[club_id_val])

        club_names = sorted(list(set(club_names_found)))
        return club_names
    except Exception as e:
        st.error(f"Error fetching clubs for leagues: {e}")
        return []
# --- End function to get club names for leagues ---

# --- Function to get date range for an asset ---
@st.cache_data(ttl=1800, show_spinner=False, max_entries=20)
def get_date_range_for_asset(_asset_obj: Asset, date_column_name: str):
    file_path = get_asset_prep_path(_asset_obj)
    if not os.path.exists(file_path):
        # st.warning(f"Data file not found, cannot determine date range: {file_path}") # Warning can be noisy if file is optional
        return None, None

    query = f"SELECT MIN(CAST({date_column_name} AS DATE)) AS min_date, MAX(CAST({date_column_name} AS DATE)) AS max_date FROM read_csv_auto('{str(file_path)}')"
    
    try:
        con = duckdb.connect(database=':memory:', read_only=True)
        result = con.execute(query).fetchdf()
        con.close()
        
        if not result.empty:
            min_date_res = result['min_date'].iloc[0]
            max_date_res = result['max_date'].iloc[0]
            
            if pd.NaT is not min_date_res and min_date_res is not None:
                if isinstance(min_date_res, pd.Timestamp):
                    min_date_res = min_date_res.date()
                elif isinstance(min_date_res, datetime): # datetime.datetime object
                    min_date_res = min_date_res.date()
            else:
                min_date_res = None # Explicitly set to None if NaT or None

            if pd.NaT is not max_date_res and max_date_res is not None:
                if isinstance(max_date_res, pd.Timestamp):
                    max_date_res = max_date_res.date()
                elif isinstance(max_date_res, datetime): # datetime.datetime object
                    max_date_res = max_date_res.date()
            else:
                max_date_res = None # Explicitly set to None if NaT or None
            
            return min_date_res, max_date_res
        return None, None
    except Exception as e:
        return None, None
# --- End function to get date range ---


# Let user select asset
dataset_names = list(td.assets.keys())
ASSET_DISPLAY_NAMES = {
    "cur_appearances": "Player Appearances",
    "cur_club_games": "Club Games",
    "cur_clubs": "Clubs",
    "cur_competitions": "Competitions",
    "cur_game_events": "Game Events",
    "cur_game_lineups": "Game Lineups",
    "cur_games": "Games",
    "cur_player_valuations": "Player Valuations",
    "cur_players": "Players",
    "cur_transfers": "Transfers",
    # Add other asset names here if they exist
}

# Use display names for selection, but keep original names for internal use
display_asset_names = [ASSET_DISPLAY_NAMES.get(name, name) for name in dataset_names]
selected_display_name = st.selectbox("Select a dataset:", display_asset_names)

# Get the original asset name corresponding to the selected display name
asset_name = dataset_names[display_asset_names.index(selected_display_name)]
asset = td.assets[asset_name]

# --- Define user-friendly column names ---
FRIENDLY_COLUMN_NAMES = {
    "game_id": "Game ID",
    "competition_id": "Competition ID",
    "season": "Season",
    "round": "Round",
    "date": "Date",
    "home_club_id": "Home Club ID",
    "away_club_id": "Away Club ID",
    "home_club_goals": "Home Club Goals",
    "away_club_goals": "Away Club Goals",
    "home_club_position": "Home Club Position",
    "away_club_position": "Away Club Position",
    "home_club_manager_name": "Home Club Manager",
    "away_club_manager_name": "Away Club Manager",
    "stadium": "Stadium",
    "attendance": "Attendance",
    "referee": "Referee",
    "url": "URL",
    # For 'cur_players'
    "player_id": "Player ID",
    "current_club_id": "Current Club ID",
    "current_club_name": "Current Club",
    "country_of_birth": "Country of Birth",
    "city_of_birth": "City of Birth",
    "country_of_citizenship": "Country of Citizenship",
    "date_of_birth": "Date of Birth",
    "sub_position": "Sub-Position",
    "foot": "Preferred Foot",
    "height_in_cm": "Height (cm)",
    "market_value_in_eur": "Market Value (EUR)",
    "highest_market_value_in_eur": "Highest Market Value (EUR)",
    # For 'cur_transfers'
    "transfer_date": "Transfer Date",
    "transfer_season": "Transfer Season",
    "from_club_id": "From Club ID",
    "to_club_id": "To Club ID",
    "from_club_name": "From Club",
    "to_club_name": "To Club",
    "transfer_fee": "Transfer Fee (EUR)",
    # Add more mappings for other assets and their columns
}

# --- DUCKDB Data Loading and Filtering ---

# Define which assets have a primary date column and what that column is
date_filterable_assets = {
    "cur_games": "date",
    "cur_appearances": "date",
    "cur_player_valuations": "date",
    "cur_transfers": "transfer_date",
}

# Team (Club) Filter Configuration
team_filterable_assets = {
    "cur_games": {"cols": ["home_club_id", "away_club_id"], "type": "any"},
    "cur_players": {"cols": ["current_club_id"], "type": "single"},
    "cur_appearances": {"cols": ["player_club_id"], "type": "single"},
    "cur_club_games": {"cols": ["club_id"], "type": "single"},
    "cur_transfers": {"cols": ["from_club_id", "to_club_id"], "type": "any"}
}

# Get filter values from UI
st.sidebar.subheader("Apply Filters")

# --- League Filter Setup ---
league_display_names = list(TOP_LEAGUES.keys())
selected_leagues_display = st.sidebar.multiselect(
    "Filter by Top League (teams from last 20 years):", 
    options=league_display_names,
    key="league_filter"
)
selected_league_codes = [TOP_LEAGUES[name] for name in selected_leagues_display]

# Determine date range for league's teams
current_year = datetime.now().year
start_year_for_leagues = current_year - 20
# --- End League Filter Setup ---

# --- Global Date Filter Setup ---
# Use broad defaults - do NOT query data files immediately when asset changes
global_min_val_for_input = datetime(1990, 1, 1).date()
global_max_val_for_input = datetime.now().date() 
initial_date_range_value = [global_min_val_for_input, global_max_val_for_input]

# Set date filter label based on asset type without loading data
if asset_name in date_filterable_assets:
    date_col_for_asset = date_filterable_assets[asset_name]
    date_filter_label = f"Filter by '{FRIENDLY_COLUMN_NAMES.get(date_col_for_asset, date_col_for_asset)}':"
else:
    date_filter_label = "Date Filter (asset not date-filterable)"

# Note: We deliberately do NOT call get_date_range_for_asset() here 
# to avoid loading data files immediately when user changes asset selection

# SIMPLIFIED DATE INPUT - Use separate start and end date inputs for reliability
# This replaces the problematic st.date_input with value as tuple that caused 
# "ValueError: cannot unpack non-iterable datetime.date object" in Streamlit Cloud
st.sidebar.subheader(date_filter_label)

# Use separate date inputs to avoid the tuple/single date issue
start_date_input = st.sidebar.date_input(
    "Start Date:",
    value=initial_date_range_value[0],
    min_value=global_min_val_for_input,
    max_value=global_max_val_for_input,
    key="start_date_filter"
)

end_date_input = st.sidebar.date_input(
    "End Date:",
    value=initial_date_range_value[1],
    min_value=global_min_val_for_input,
    max_value=global_max_val_for_input,
    key="end_date_filter"
)

# Ensure start_date <= end_date with clear user feedback
if start_date_input > end_date_input:
    st.sidebar.error("⚠️ Start date must be before or equal to end date!")
    st.sidebar.info("Automatically swapping dates...")
    # Swap them automatically
    start_date_input, end_date_input = end_date_input, start_date_input

# Create the final date range tuple
selected_date_range_ui = (start_date_input, end_date_input)

# --- End Global Date Filter Setup ---

# Team (Club) Filter UI - Only available if club filtering is enabled
selected_club_names_ui = [] # Initialize before use

if load_clubs_for_filtering and asset_name in team_filterable_assets:
    team_filter_config = team_filterable_assets[asset_name]
    filter_key_club = f"club_filter_{asset_name}" # Unique key per asset
    
    # Dynamically populate club list based on selected leagues
    clubs_for_selection = available_club_names # Default to all clubs

    if selected_league_codes:
        # Ensure club_id_to_name is populated (it comes from load_club_data)
        if not club_id_to_name:
            st.sidebar.warning("Club name mapping is not available. Cannot filter by league teams. Showing all clubs.")
            clubs_for_selection = available_club_names
        else:
            league_specific_clubs = get_club_names_for_leagues(
                selected_league_codes, 
                td, 
                club_id_to_name, 
                start_year_for_leagues, 
                current_year
            )
            if league_specific_clubs:
                clubs_for_selection = league_specific_clubs
            else:
                st.sidebar.warning("No clubs found for the selected leagues and recent seasons. Showing all available clubs.")
                clubs_for_selection = available_club_names # Fallback to all if no specific clubs found

    if clubs_for_selection: # Only show multiselect if there are clubs to select
        selected_club_names_ui = st.sidebar.multiselect(
            "Filter by Club(s):",
            options=sorted(list(set(clubs_for_selection))), # Ensure unique and sorted options
            key=filter_key_club
        )
    else:
        st.sidebar.info("No clubs available for filtering for the current selection.")
        selected_club_names_ui = []
        
elif asset_name in team_filterable_assets and not load_clubs_for_filtering:
    st.sidebar.info(f"🏟️ Club filtering available for '{ASSET_DISPLAY_NAMES.get(asset_name, asset_name)}' - enable it above.")
    selected_club_names_ui = []
else:
    st.sidebar.info(f"Club filtering not applicable for the '{ASSET_DISPLAY_NAMES.get(asset_name, asset_name)}' dataset.")
    selected_club_names_ui = []

# Function to process data in chunks for memory efficiency
def process_data_in_chunks(_asset_obj: Asset, filters: dict, chunk_years: int = 5) -> dict:
    """Process large datasets in year-based chunks to minimize memory usage"""
    
    # Check if this is a date-filterable asset with date range
    if not filters.get("date_filter_col") or not filters.get("date_range"):
        # If no date filtering, fall back to regular processing with limits
        return load_data_with_duckdb(_asset_obj, filters)
    
    start_date, end_date = filters["date_range"]
    start_year = start_date.year
    end_year = end_date.year
    
    # If date range is small enough, process normally
    if (end_year - start_year) <= chunk_years:
        return load_data_with_duckdb(_asset_obj, filters)
    
    # Process in chunks
    st.info(f"📦 Large date range detected ({start_year}-{end_year}). Processing in {chunk_years}-year chunks for memory efficiency.")
    
    all_chunks = []
    total_rows = 0
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    chunk_start_year = start_year
    chunk_count = 0
    total_chunks = ((end_year - start_year) // chunk_years) + 1
    
    try:
        while chunk_start_year <= end_year:
            chunk_end_year = min(chunk_start_year + chunk_years - 1, end_year)
            chunk_count += 1
            
            status_text.text(f"Processing chunk {chunk_count}/{total_chunks}: {chunk_start_year}-{chunk_end_year}")
            
            # Create chunk-specific filters
            chunk_filters = filters.copy()
            chunk_start_date = date(chunk_start_year, 1, 1)
            chunk_end_date = date(chunk_end_year, 12, 31)
            
            # Ensure chunk dates don't exceed original range
            chunk_start_date = max(chunk_start_date, start_date)
            chunk_end_date = min(chunk_end_date, end_date)
            
            chunk_filters["date_range"] = (chunk_start_date, chunk_end_date)
            
            # Process this chunk
            chunk_result = load_data_with_duckdb(_asset_obj, chunk_filters)
            
            if chunk_result['error']:
                return chunk_result  # Return error immediately
            
            chunk_data = chunk_result['data']
            if not chunk_data.empty:
                all_chunks.append(chunk_data)
                total_rows += len(chunk_data)
                
                # Clear chunk data from memory immediately after appending
                del chunk_data
                gc.collect()
            
            # Update progress
            progress_bar.progress(chunk_count / total_chunks)
            
            chunk_start_year += chunk_years
        
        progress_bar.progress(1.0)
        status_text.text("Combining chunks...")
        
        # Combine all chunks
        if all_chunks:
            combined_data = pd.concat(all_chunks, ignore_index=True)
            # Clear chunk list from memory
            del all_chunks
            gc.collect()
            
            status_text.text(f"✅ Processed {total_rows:,} rows across {chunk_count} chunks")
            return {'data': combined_data, 'query': f"Chunked processing ({chunk_count} chunks)", 'error': None, 'total_rows_available': total_rows}
        else:
            status_text.text("No data found in any chunks")
            return {'data': pd.DataFrame(), 'query': "Chunked processing (no data)", 'error': None, 'total_rows_available': 0}
            
    except Exception as e:
        status_text.text(f"❌ Error during chunked processing: {str(e)}")
        # Clean up any remaining chunks
        if 'all_chunks' in locals():
            del all_chunks
        gc.collect()
        return {'data': pd.DataFrame(), 'query': "Chunked processing (failed)", 'error': f"Chunked processing failed: {str(e)}", 'total_rows_available': 0}
    
    finally:
        # Always clean up
        gc.collect()

# Function to load and filter data using DuckDB
@st.cache_data(ttl=1800, show_spinner=False, max_entries=5)
def load_data_with_duckdb(_asset_obj: Asset, filters: dict) -> dict:
    """Load and filter data with simplified parameter handling and memory management"""
    file_path = get_asset_prep_path(_asset_obj)
    if not os.path.exists(file_path):
        return {'data': pd.DataFrame(), 'query': "", 'error': f"Data file not found: {file_path}", 'row_count': 0}

    # Check file size before attempting to load
    try:
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb > 10:  # If file is larger than 10MB, be extra cautious
            st.warning(f"⚠️ Large data file detected ({file_size_mb:.1f} MB). Processing with conservative limits.")
    except:
        pass  # Continue if we can't check file size

    # Dataset-specific memory limits for Streamlit Cloud safety
    asset_name = getattr(_asset_obj, 'name', 'unknown')
    DATASET_LIMITS = {
        'cur_transfers': 25000,  # Transfers dataset is large, be very conservative
        'cur_player_valuations': 25000,  # Valuations can be large too
        'cur_appearances': 30000,  # Appearances can be very large
        'default': 50000  # Default limit for other datasets
    }
    
    MAX_ROWS = DATASET_LIMITS.get(asset_name, DATASET_LIMITS['default'])
    st.info(f"ℹ️ Using conservative limit of {MAX_ROWS:,} rows for {asset_name} dataset to ensure stability.")
    
    query_parts = [f"SELECT * FROM read_csv_auto('{str(file_path)}')"]
    conditions = []

    # Date condition with direct string interpolation (safer for DuckDB)
    if filters.get("date_filter_col") and filters.get("date_range"):
        date_filter_col = filters["date_filter_col"]
        date_range = filters["date_range"]
        if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
            start_date, end_date = date_range
            if isinstance(start_date, date) and isinstance(end_date, date):
                start_date_str = start_date.strftime('%Y-%m-%d')
                end_date_str = end_date.strftime('%Y-%m-%d')
                conditions.append(f'CAST("{date_filter_col}" AS DATE) >= \'{start_date_str}\' AND CAST("{date_filter_col}" AS DATE) <= \'{end_date_str}\'')
            else:
                return {'data': pd.DataFrame(), 'query': "", 'error': f"Invalid date types: start={type(start_date)}, end={type(end_date)}", 'row_count': 0}
        else:
            return {'data': pd.DataFrame(), 'query': "", 'error': f"Invalid date range format: {type(date_range)}, length={len(date_range) if hasattr(date_range, '__len__') else 'N/A'}", 'row_count': 0}

    # Club condition with direct string interpolation
    if filters.get("club_filter_config") and filters.get("selected_clubs") and filters.get("club_name_map"):
        club_filter_config = filters["club_filter_config"]
        selected_clubs = filters["selected_clubs"]
        club_name_map = filters["club_name_map"]
        selected_club_ids = [club_name_map[name] for name in selected_clubs if name in club_name_map]
        if selected_club_ids:
            club_cols_to_check = club_filter_config["cols"]
            # Create IN clause with proper escaping
            club_ids_str = ", ".join([str(club_id) for club_id in selected_club_ids])
            club_conditions_list = []
            for col in club_cols_to_check:
                club_conditions_list.append(f'"{col}" IN ({club_ids_str})')
            if club_conditions_list:
                if club_filter_config["type"] == "single" and club_conditions_list:
                    conditions.append(club_conditions_list[0])
                elif club_filter_config["type"] == "any" and club_conditions_list:
                    conditions.append(f"({' OR '.join(club_conditions_list)})")

    if conditions:
        query_parts.append("WHERE " + " AND ".join(conditions))
    
    # Add LIMIT to prevent memory issues in cloud environments
    # First, let's check if we need to limit the results
    count_query = f"SELECT COUNT(*) as row_count FROM ({' '.join(query_parts)})"
    final_query = " ".join(query_parts)

    try:
        con = duckdb.connect(database=':memory:', read_only=False)
        
        # Check row count first to prevent memory issues
        count_result = con.execute(count_query).fetchdf()
        row_count = count_result['row_count'].iloc[0] if not count_result.empty else 0
        
        # More aggressive limits for known large datasets
        if asset_name in ['cur_transfers', 'cur_appearances', 'cur_player_valuations']:
            MAX_QUERY_ROWS = 100000  # Even more conservative for large datasets
        else:
            MAX_QUERY_ROWS = 200000  # Standard limit for other datasets
            
        if row_count > MAX_QUERY_ROWS:
            final_query += f" LIMIT {MAX_QUERY_ROWS}"
            
        df_result = con.execute(final_query).fetchdf()
        con.close()
        gc.collect()
        return {'data': df_result, 'query': final_query, 'error': None, 'total_rows_available': row_count}
    
    except MemoryError as e:
        if 'con' in locals():
            con.close()
        gc.collect()
        return {'data': pd.DataFrame(), 'query': final_query, 'error': f"Memory error: Dataset too large for available memory. Try applying more filters to reduce data size.", 'total_rows_available': 0}
    
    except Exception as e:
        if 'con' in locals():
            con.close()
        gc.collect()
        error_msg = str(e)
        if 'memory' in error_msg.lower() or 'out of memory' in error_msg.lower():
            return {'data': pd.DataFrame(), 'query': final_query, 'error': f"Memory constraint: {error_msg}. Try applying filters to reduce dataset size.", 'total_rows_available': 0}
        else:
            return {'data': pd.DataFrame(), 'query': final_query, 'error': f"Query failed: {error_msg}", 'total_rows_available': 0}
    
    finally:
        gc.collect()  # Clean up memory

# Determine filter parameters for the backend function
# These are determined based on UI selections before the "Prepare" button is necessarily clicked,
# as they are needed for UI elements like the date picker's label and bounds.
date_col_to_filter = date_filterable_assets.get(asset_name)
club_config_to_filter = team_filterable_assets.get(asset_name) if available_club_names else None

# Initialize session state for prepared data if not already present
if 'data_prepared_for_download' not in st.session_state:
    st.session_state.data_prepared_for_download = False
if 'excel_bytes_for_download' not in st.session_state:
    st.session_state.excel_bytes_for_download = None
if 'excel_filename_for_download' not in st.session_state:
    st.session_state.excel_filename_for_download = ""

# --- Button to trigger data loading and Excel preparation ---
if st.button("Prepare Data for Download", key="prepare_data_button"):
    # Reset flags and data before attempting preparation
    st.session_state.data_prepared_for_download = False
    st.session_state.excel_bytes_for_download = None
    st.session_state.excel_filename_for_download = ""
    
    # Force garbage collection before starting
    gc.collect()

    # Prepare filters for DuckDB function based on current UI state
    filters_for_duckdb = {}
    
    # Enhanced date filter validation
    if date_col_to_filter and selected_date_range_ui:
        if isinstance(selected_date_range_ui, (tuple, list)) and len(selected_date_range_ui) == 2:
            start_date, end_date = selected_date_range_ui
            if isinstance(start_date, date) and isinstance(end_date, date):
                filters_for_duckdb["date_filter_col"] = date_col_to_filter
                filters_for_duckdb["date_range"] = selected_date_range_ui
            else:
                st.error(f"Invalid date types: start={type(start_date)}, end={type(end_date)}")
                st.stop()
        else:
            st.error(f"Invalid date range format. Expected tuple of 2 dates, got: {type(selected_date_range_ui)}")
            st.stop()

    if club_config_to_filter and selected_club_names_ui is not None:
        filters_for_duckdb["club_filter_config"] = club_config_to_filter
        filters_for_duckdb["selected_clubs"] = selected_club_names_ui
        filters_for_duckdb["club_name_map"] = club_name_to_id

    # Pre-check for large datasets to warn users
    LARGE_DATASETS = ['cur_transfers', 'cur_appearances', 'cur_player_valuations']
    if asset_name in LARGE_DATASETS and not filters_for_duckdb.get("date_filter_col") and not filters_for_duckdb.get("selected_clubs"):
        st.warning(f"⚠️ {asset_name} is a large dataset. For better performance and stability, consider applying date or club filters before preparing data.")
        if not st.checkbox(f"I understand - proceed with {asset_name} anyway", key=f"proceed_{asset_name}"):
            st.info("Apply some filters above and try again, or check the box to proceed without filters.")
            st.stop()

    with st.spinner("Preparing data... This may take a moment."):
        try:
            result_info = load_data_with_duckdb(
                asset, 
                filters_for_duckdb
            )
        except Exception as e:
            st.error(f"❌ Error loading data: {str(e)}")
            st.info("This might be due to memory constraints. Try applying more filters to reduce the dataset size.")
            gc.collect()
            st.stop()

        df_filtered = result_info['data']
        query_executed = result_info['query']
        error_message = result_info['error']
        total_rows_available = result_info.get('total_rows_available', len(df_filtered))

        if error_message:
            st.error(error_message)
            if query_executed: # Show query only if one was attempted and is not empty
                st.code(query_executed, language='sql')
        elif df_filtered.empty:
            st.warning("No data matches the current filters. Please adjust filters and try preparing again.")
            if query_executed:
                st.code(query_executed, language='sql')
        else:
            # Show info about data availability
            if total_rows_available > len(df_filtered):
                st.info(f"ℹ️ Found {total_rows_available:,} total rows, but limiting query to {len(df_filtered):,} rows for performance.")
            
            # Check data size to prevent memory issues in Streamlit Cloud
            num_rows = len(df_filtered)
            num_cols = len(df_filtered.columns)
            estimated_size_mb = (num_rows * num_cols * 8) / (1024 * 1024)  # Rough estimate
            
            # Dataset-specific export limits for Streamlit Cloud stability
            EXPORT_LIMITS = {
                'cur_transfers': 20000,  # Very conservative for transfers
                'cur_player_valuations': 20000,  # Conservative for valuations
                'cur_appearances': 25000,  # Conservative for appearances
                'default': 40000  # Default limit reduced from 50k
            }
            
            MAX_ROWS_CLOUD = EXPORT_LIMITS.get(asset_name, EXPORT_LIMITS['default'])
            if num_rows > MAX_ROWS_CLOUD:
                st.warning(f"⚠️ Dataset is large ({num_rows:,} rows). For stability, limiting export to first {MAX_ROWS_CLOUD:,} rows for {asset_name}.")
                df_filtered = df_filtered.head(MAX_ROWS_CLOUD)
                num_rows = len(df_filtered)
            
            st.info(f"📊 Preparing {num_rows:,} rows × {num_cols} columns (est. {estimated_size_mb:.1f} MB)")
            
            try:
                # Data is good, prepare Excel with memory management
                export_df = df_filtered.copy()
                friendly_export_df_columns = [FRIENDLY_COLUMN_NAMES.get(col, col) for col in export_df.columns]
                export_df.columns = friendly_export_df_columns

                # Use memory-efficient Excel creation
                output = BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl', options={'remove_timezone': True}) as writer:
                    export_df.to_excel(writer, index=False, sheet_name='Data')
                
                excel_bytes = output.getvalue()
                output.close()  # Explicitly close BytesIO
                
                # Check file size before storing in session state
                excel_size_mb = len(excel_bytes) / (1024 * 1024)
                MAX_FILE_SIZE_MB = 100  # Maximum file size for Streamlit Cloud
                
                if excel_size_mb > MAX_FILE_SIZE_MB:
                    del excel_bytes
                    gc.collect()
                    st.error(f"❌ Generated file is too large ({excel_size_mb:.1f} MB). Maximum allowed: {MAX_FILE_SIZE_MB} MB. Please apply more filters to reduce data size.")
                else:
                    # Clean up intermediate dataframes
                    del export_df
                    del df_filtered
                    gc.collect()
                    
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    excel_filename = f"transfermarkt_{asset_name}_{timestamp}.xlsx"
                    
                    # Store in session state for download
                    st.session_state.excel_bytes_for_download = excel_bytes
                    st.session_state.excel_filename_for_download = excel_filename
                    st.session_state.data_prepared_for_download = True
                    
                    st.success(f"✅ Data prepared successfully! {num_rows:,} rows ready for download (Excel file: {excel_size_mb:.1f} MB)")
                
            except MemoryError:
                st.error("❌ Not enough memory to create Excel file. Try reducing the date range or applying more filters.")
                gc.collect()
            except Exception as e:
                st.error(f"❌ Error creating Excel file: {str(e)}")
                gc.collect()
            finally:
                # Always clean up memory
                gc.collect()

# --- Download button section ---
# This section is evaluated on every run. The download button appears if data is ready.
if st.session_state.data_prepared_for_download and st.session_state.excel_bytes_for_download:
    try:
        excel_size_mb = len(st.session_state.excel_bytes_for_download) / (1024 * 1024)
        st.download_button(
            label=f"📥 Download Excel File ({excel_size_mb:.1f} MB)",
            data=st.session_state.excel_bytes_for_download,
            file_name=st.session_state.excel_filename_for_download,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="final_download_excel_button",
            help="Click to download the prepared Excel file"
        )
        
        # Add a button to clear the prepared data to free memory
        if st.button("🗑️ Clear Prepared Data", help="Free up memory by clearing the prepared Excel file"):
            st.session_state.data_prepared_for_download = False
            st.session_state.excel_bytes_for_download = None
            st.session_state.excel_filename_for_download = ""
            gc.collect()
            st.success("✅ Prepared data cleared. Memory freed up.")
            st.rerun()
            
    except Exception as e:
        st.error(f"❌ Error with download: {str(e)}")
        # Clear corrupted data
        st.session_state.data_prepared_for_download = False
        st.session_state.excel_bytes_for_download = None
        st.session_state.excel_filename_for_download = ""
        gc.collect()
        
elif not st.session_state.data_prepared_for_download and not st.session_state.excel_bytes_for_download:
    st.info("Select your dataset and filters, then click 'Prepare Data for Download'.")

# Clean up memory periodically
if 'cleanup_counter' not in st.session_state:
    st.session_state.cleanup_counter = 0
st.session_state.cleanup_counter += 1
if st.session_state.cleanup_counter % 10 == 0:  # Every 10 page loads
    gc.collect()
