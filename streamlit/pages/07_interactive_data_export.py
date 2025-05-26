import streamlit as st
import pandas as pd
from io import BytesIO
import os
from datetime import datetime # Ensure datetime is imported if not already
import sys # Add sys import

# --- Add parent directory to sys.path to find utils.py ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# --- End add parent directory ---

# --- Add duckdb import ---
import duckdb

# --- Add Asset import for type hinting ---
from transfermarkt_datasets.core.asset import Asset
from transfermarkt_datasets.core.dataset import Dataset # Added for type hinting

from utils import load_td # Assuming utils.py is now findable

st.set_page_config(page_title="Transfermarkt Database", page_icon="⚽") # MODIFIED
st.title("⚽ Transfermarkt Database") # MODIFIED

st.markdown("""
Explore the Transfermarkt database, apply filters, and export the results to Excel.
""") # MODIFIED

# Define Top 5 Leagues and their known competition codes
# These codes (e.g., 'GB1') should match 'competition_id' in your datasets
TOP_LEAGUES = {
    "Premier League (England)": "GB1",
    "La Liga (Spain)": "ES1",
    "Bundesliga (Germany)": "L1",
    "Serie A (Italy)": "IT1",
    "Ligue 1 (France)": "FR1",
}

# Load the dataset object (loads all assets)
# @st.cache_data # Caching td is good
def get_dataset(): # Wrapper for caching
    return load_td()

td = get_dataset()

# --- Enhanced Setup for Filters ---
# Load clubs data for team filtering
# @st.cache_data # Cache clubs_df and mappings
def load_club_data(dataset):
    clubs_asset = dataset.assets.get("cur_clubs")
    clubs_df_local = None
    club_id_to_name_local = {}
    club_name_to_id_local = {}
    available_club_names_local = []

    if clubs_asset:
        try:
            # For club data, direct load is fine as it's likely smaller and needed for UI
            clubs_asset.load_from_prep() 
            clubs_df_local = clubs_asset.prep_df
            if clubs_df_local is not None and 'club_id' in clubs_df_local.columns and 'name' in clubs_df_local.columns:
                available_club_names_local = sorted(clubs_df_local['name'].dropna().unique())
                # Ensure club_id is string for dictionary keys if they are mixed type, though usually int
                # For safety, ensure club_id used in dicts is consistently typed if issues arise.
                temp_id_to_name = clubs_df_local.dropna(subset=['club_id', 'name']).set_index('club_id')['name'].to_dict()
                club_name_to_id_local = {
                    name: clubs_df_local[clubs_df_local['name'] == name]['club_id'].iloc[0] 
                    for name in available_club_names_local
                }
                # Ensure club_id_to_name_local keys are of the same type as used elsewhere (e.g. from games.csv)
                club_id_to_name_local = {
                    club_id: name for name, club_id in club_name_to_id_local.items()
                }

        except FileNotFoundError:
            st.sidebar.warning("Clubs data file (cur_clubs) not found. Team filtering will be unavailable.")
        except Exception as e:
            st.sidebar.error(f"Could not load clubs data for filtering: {e}")
    return clubs_df_local, club_id_to_name_local, club_name_to_id_local, available_club_names_local

clubs_df, club_id_to_name, club_name_to_id, available_club_names = load_club_data(td)

# --- End Enhanced Setup for Filters ---

# --- Function to get club names for selected leagues and seasons ---
@st.cache_data(show_spinner="Fetching clubs for selected leagues...")
def get_club_names_for_leagues(
    _selected_league_codes: list, 
    _td_dataset: Dataset, # Use the specific type hint for td
    _club_id_to_name_map: dict,
    _start_year: int, 
    _end_year: int
):
    print(f"DEBUG: get_club_names_for_leagues called with leagues: {_selected_league_codes}, years: {_start_year}-{_end_year}") # ADDED

    if not _selected_league_codes:
        print("DEBUG: get_club_names_for_leagues: No selected league codes, returning empty list.") # ADDED
        return []

    games_asset = _td_dataset.assets.get("cur_games") # MODIFIED from "games"
    if not games_asset:
        st.warning("Games asset ('cur_games') not found in dataset.")
        print("DEBUG: get_club_names_for_leagues: 'cur_games' asset not found. Available keys:", list(_td_dataset.assets.keys())) # ADDED
        return []
    
    games_file_path = games_asset.prep_path
    print(f"DEBUG: get_club_names_for_leagues: games_file_path: {games_file_path}") # ADDED
    if not os.path.exists(games_file_path):
        st.warning(f"Games data file not found: {games_file_path}")
        print(f"DEBUG: get_club_names_for_leagues: File not found at {games_file_path}") # ADDED
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
    
    print(f"DEBUG: Executing get_club_names_for_leagues query: {query}") # UNCOMMENTED & MODIFIED

    try:
        con = duckdb.connect(database=':memory:', read_only=False) # MODIFIED read_only to False
        club_ids_df = con.execute(query).fetchdf()
        con.close()

        print(f"DEBUG: get_club_names_for_leagues: club_ids_df.info()") # ADDED
        # club_ids_df.info(verbose=True) # This prints to stdout, captured by Streamlit
        # For a cleaner log in the tool output, let's capture it as a string if possible, or rely on terminal.
        # For now, let's assume print to terminal is fine. If not, we can adjust.
        if hasattr(club_ids_df, 'info'):
            # Redirect stdout to capture df.info()
            from io import StringIO
            buffer = StringIO()
            sys.stdout = buffer
            club_ids_df.info(verbose=True)
            sys.stdout = sys.__stdout__ # Reset stdout
            print(f"DEBUG: get_club_names_for_leagues: club_ids_df.info() output:\n{buffer.getvalue()}")

        print(f"DEBUG: get_club_names_for_leagues: club_ids_df.head():\\n{club_ids_df.head().to_string()}") # ADDED
        print(f"DEBUG: get_club_names_for_leagues: Number of club_ids returned by query: {len(club_ids_df)}") # ADDED

        if club_ids_df.empty:
            print("DEBUG: get_club_names_for_leagues: Query returned no club IDs.") # ADDED
            return []
        
        # Debugging the map and IDs
        if _club_id_to_name_map:
            sample_map_key = next(iter(_club_id_to_name_map), None) # ADDED default None
            if sample_map_key is not None: # ADDED check
                print(f"DEBUG: get_club_names_for_leagues: Sample key from _club_id_to_name_map: {sample_map_key} (type: {type(sample_map_key)})")
        else:
            print("DEBUG: get_club_names_for_leagues: _club_id_to_name_map is empty!") # ADDED
            return [] 

        club_names_found = []
        # Ensure club_id from df matches type of keys in _club_id_to_name_map
        unique_club_ids_from_query = club_ids_df['club_id'].dropna().unique()
        print(f"DEBUG: get_club_names_for_leagues: Unique club IDs from query ({len(unique_club_ids_from_query)}): {list(unique_club_ids_from_query)[:10]}") # ADDED first 10

        for club_id_val in unique_club_ids_from_query: 
            # Example type print for the first ID encountered
            if not club_names_found and unique_club_ids_from_query.size > 0: # Print type for the first actual ID
                 print(f"DEBUG: get_club_names_for_leagues: Processing first club_id_val: {club_id_val} (type: {type(club_id_val)})")


            if club_id_val in _club_id_to_name_map:
                club_names_found.append(_club_id_to_name_map[club_id_val])
        
        if not club_names_found and not club_ids_df.empty: # ADDED check for non-empty df
            print("DEBUG: get_club_names_for_leagues: No club names found after mapping. This could be due to type mismatches or missing IDs in the map.")
            unmapped_ids = [id_val for id_val in unique_club_ids_from_query if id_val not in _club_id_to_name_map]
            if unmapped_ids:
                print(f"DEBUG: get_club_names_for_leagues: First few unmapped IDs from query: {unmapped_ids[:5]}")
                if _club_id_to_name_map and sample_map_key is not None: # Check sample_map_key again
                     print(f"DEBUG: get_club_names_for_leagues: First few keys in _club_id_to_name_map: {list(_club_id_to_name_map.keys())[:5]}")


        club_names = sorted(list(set(club_names_found))) # Use set to ensure uniqueness of names
        print(f"DEBUG: get_club_names_for_leagues: Found {len(club_names)} unique club names. First 20: {club_names[:20]}") # ADDED count and first 20
        return club_names
    except Exception as e:
        st.error(f"Error fetching clubs for leagues: {e}")
        print(f"DEBUG: Error in get_club_names_for_leagues: {e}") # UNCOMMENTED & MODIFIED
        return []
# --- End function to get club names for leagues ---

# --- Function to get date range for an asset ---
@st.cache_data(show_spinner="Fetching date range...")
def get_date_range_for_asset(_asset_obj: Asset, date_column_name: str):
    file_path = _asset_obj.prep_path # MODIFIED
    if not os.path.exists(file_path):
        # st.warning(f"Data file not found, cannot determine date range: {file_path}") # Warning can be noisy if file is optional
        return None, None

    # Use the asset_name for more informative error messages if needed later
    # asset_name_for_error = _asset_obj.name # If you need it

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
        # st.error(f"Error fetching date range for {date_column_name} from asset: {e}") # Can be noisy
        # print(f"Error fetching date range for {date_column_name}: {e}") # For server logs
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

# --- Define user-friendly column names (MOVED EARLIER) ---
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
    # "name": "Player Name", # Assuming 'name' is too generic, let's use original if not specified
    "current_club_id": "Current Club ID",
    "current_club_name": "Current Club",
    "country_of_birth": "Country of Birth",
    "city_of_birth": "City of Birth",
    "country_of_citizenship": "Country of Citizenship",
    "date_of_birth": "Date of Birth",
    # "position": "Position", # Assuming 'position' is too generic
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
    "Filter by Top League (teams from last 20 years):", # Modified label
    options=league_display_names,
    key="league_filter"
)
selected_league_codes = [TOP_LEAGUES[name] for name in selected_leagues_display]

# Determine date range for league's teams
current_year = datetime.now().year
start_year_for_leagues = current_year - 20
# --- End League Filter Setup ---


# --- Global Date Filter Setup ---
# Initial broad defaults, these will be refined if a date-filterable asset is selected
global_min_val_for_input = datetime(1990, 1, 1).date()
global_max_val_for_input = datetime.now().date() 
# Attempt to retrieve persisted date range, or use a default based on initial broad values
# Streamlit's `key` handles state, `value` sets the initial state if none exists or programmatically updates.
# For the initial `value`, we'll refine it based on the selected asset below.
initial_date_range_value = (global_min_val_for_input, global_max_val_for_input)
date_filter_label = "Filter by Date" # Generic initial label

selected_date_range_ui = None # Initialize

if asset_name in date_filterable_assets:
    date_col_for_asset = date_filterable_assets[asset_name]
    min_date_from_data, max_date_from_data = get_date_range_for_asset(asset, date_col_for_asset)

    if min_date_from_data:
        global_min_val_for_input = min_date_from_data
    if max_date_from_data:
        global_max_val_for_input = max_date_from_data
    
    # The default value for the date_input should reflect the current asset's actual range
    # This is used if no value is already in st.session_state for "global_date_filter"
    # or to guide the user if they haven't interacted yet.
    initial_date_range_value = (global_min_val_for_input, global_max_val_for_input)
    date_filter_label = f"Filter by '{FRIENDLY_COLUMN_NAMES.get(date_col_for_asset, date_col_for_asset)}':"
else:
    # Asset is not date-filterable, provide a more generic label
    date_filter_label = "Date Filter (asset not date-filterable)"

selected_date_range_ui = st.sidebar.date_input(
    date_filter_label,
    value=initial_date_range_value, 
    min_value=global_min_val_for_input,
    max_value=global_max_val_for_input,
    key="global_date_filter"  # Using a single key makes the selection persist
)
# --- End Global Date Filter Setup ---

selected_club_names_ui = [] # Initialize before use

# Team (Club) Filter UI
# Dynamically populate club list based on selected leagues
clubs_for_selection = available_club_names # Default to all clubs

if selected_league_codes:
    # Ensure club_id_to_name is populated
    if not club_id_to_name: # Should be populated by load_club_data
        st.sidebar.warning("Club ID to Name mapping not available for league filtering.")
        # Fallback or handle error appropriately
    else:
        clubs_for_selection = get_club_names_for_leagues(
            selected_league_codes,
            td, 
            club_id_to_name,
            start_year_for_leagues,
            current_year 
        )
        if not clubs_for_selection and selected_leagues_display: # If leagues selected but no clubs found
            st.sidebar.info(f"No clubs found for {', '.join(selected_leagues_display)} in the last 20 years, or data is unavailable.")


if asset_name in team_filterable_assets: # available_club_names check is implicitly handled by clubs_for_selection
    # If clubs_for_selection is empty, multiselect will show no options, which is fine.
    selected_club_names_ui = st.sidebar.multiselect(
        "Filter by Club(s):",
        options=clubs_for_selection, # Use dynamically generated list
        key=f"club_filter_{asset_name}" 
        # Streamlit should handle selected values correctly if options change.
        # If a selected club is no longer in options, it will be deselected.
    )
else:
    selected_club_names_ui = [] # Ensure it's defined even if no filter is shown

# Function to load and filter data using DuckDB
@st.cache_data(show_spinner="Loading and filtering data...")
def load_data_with_duckdb(_asset_obj: Asset, filters: dict) -> dict: # Return a dict
    file_path = _asset_obj.prep_path
    
    # This print will show up in the terminal running streamlit, helping debug
    # print(f"Attempting to load data for asset: {_asset_obj.name}, file: {file_path}")

    if not os.path.exists(file_path):
        # print(f"Data file not found: {file_path}") # Server-side log
        return {'data': pd.DataFrame(), 'query': "", 'error': f"Data file not found: {file_path}"}

    query_parts = [f"SELECT * FROM read_csv_auto('{str(file_path)}')"]
    conditions = []
    params = {}

    # Date condition
    if filters.get("date_filter_col") and filters.get("date_range") and len(filters["date_range"]) == 2:
        date_filter_col = filters["date_filter_col"]
        date_range = filters["date_range"]
        start_date, end_date = date_range
        if start_date and end_date: # Ensure dates are not None
            params['start_date'] = start_date.strftime('%Y-%m-%d')
            params['end_date'] = end_date.strftime('%Y-%m-%d')
            # Quote column names for safety
            conditions.append(f'CAST("{date_filter_col}" AS DATE) >= $start_date AND CAST("{date_filter_col}" AS DATE) <= $end_date')
        else:
            # print("Date range contains None values, skipping date filter.") # Server-side log
            pass


    # Club condition
    if filters.get("club_filter_config") and filters.get("selected_clubs") and filters.get("club_name_map"):
        club_filter_config = filters["club_filter_config"]
        selected_clubs = filters["selected_clubs"]
        club_name_map = filters["club_name_map"]
        
        selected_club_ids = [club_name_map[name] for name in selected_clubs if name in club_name_map]
        if selected_club_ids:
            club_cols_to_check = club_filter_config["cols"]
            
            param_club_ids = tuple(selected_club_ids)
            params['club_ids'] = param_club_ids
            
            club_conditions_list = []
            for col in club_cols_to_check:
                # Quote column names for safety
                club_conditions_list.append(f'"{col}" IN $club_ids') 
            
            if club_conditions_list:
                if club_filter_config["type"] == "single" and club_conditions_list: # ensure list not empty
                    conditions.append(club_conditions_list[0])
                elif club_filter_config["type"] == "any" and club_conditions_list: # ensure list not empty
                    conditions.append(f"({' OR '.join(club_conditions_list)})")
    
    if conditions:
        query_parts.append("WHERE " + " AND ".join(conditions))
    
    final_query = " ".join(query_parts)
    
    # Server-side logging for debugging the exact query and params
    print(f"Executing DuckDB query: {final_query}")
    print(f"With params: {params}")
    
    try:
        con = duckdb.connect(database=':memory:', read_only=False)
        df_result = con.execute(final_query, params).fetchdf()
        con.close()
        return {'data': df_result, 'query': final_query, 'error': None}
    except Exception as e:
        # print(f"DuckDB query failed. Query: {final_query}, Params: {params}, Error: {e}") # Server-side log
        return {'data': pd.DataFrame(), 'query': final_query, 'error': f"DuckDB query failed: {e}"}

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

    # Prepare filters for DuckDB function based on current UI state
    filters_for_duckdb = {}
    if date_col_to_filter and selected_date_range_ui and len(selected_date_range_ui) == 2:
        filters_for_duckdb["date_filter_col"] = date_col_to_filter
        filters_for_duckdb["date_range"] = selected_date_range_ui

    if club_config_to_filter and selected_club_names_ui is not None:
        filters_for_duckdb["club_filter_config"] = club_config_to_filter
        filters_for_duckdb["selected_clubs"] = selected_club_names_ui
        filters_for_duckdb["club_name_map"] = club_name_to_id

    with st.spinner("Preparing data... This may take a moment."):
        result_info = load_data_with_duckdb(
            asset, 
            filters_for_duckdb
        )

        df_filtered = result_info['data']
        query_executed = result_info['query']
        error_message = result_info['error']

        if error_message:
            st.error(error_message)
            if query_executed: # Show query only if one was attempted and is not empty
                st.code(query_executed, language='sql')
        elif df_filtered.empty:
            # Display warning only if there wasn't a preceding error
            if not error_message: 
                st.warning("No data matches the current filters. Please adjust filters and try preparing again.")
        else:
            # Data is good, prepare Excel
            export_df = df_filtered.copy()
            friendly_export_df_columns = [FRIENDLY_COLUMN_NAMES.get(col, col) for col in export_df.columns]
            export_df.columns = friendly_export_df_columns

            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                export_df.to_excel(writer, index=False, sheet_name=asset_name)
            
            st.session_state.excel_bytes_for_download = output.getvalue()
            st.session_state.excel_filename_for_download = f"{asset_name}.xlsx"
            st.session_state.data_prepared_for_download = True # Set flag on success
            st.success("Data is ready! Click the download button below.")

# --- Download button section ---
# This section is evaluated on every run. The download button appears if data is ready.
if st.session_state.data_prepared_for_download and st.session_state.excel_bytes_for_download:
    st.download_button(
        label="Download Excel File",
        data=st.session_state.excel_bytes_for_download,
        file_name=st.session_state.excel_filename_for_download,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="final_download_excel_button"
    )
elif not st.session_state.data_prepared_for_download and not st.session_state.excel_bytes_for_download :
    # Show this message only if no attempt to prepare has been made yet, or if a previous attempt cleared the flags
    # and didn't result in an error message being shown immediately above by the prepare block.
    # This avoids showing this info message if an error/warning from the "Prepare" step is already visible.
    # A more robust way might involve checking if the "prepare_data_button" was just clicked and failed.
    # For now, this condition should cover most "initial state" or "reset state" scenarios.
    st.info("Select your dataset and filters, then click 'Prepare Data for Download'.")

# The old df_filtered, query_executed, error_message variables are now local to the "Prepare" button block.
# The st.stop() calls are removed as conditional rendering handles flow.
# The final st.success message is also moved into the "Prepare" button logic.

