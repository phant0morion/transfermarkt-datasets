# Debug version of data export to help identify issues
import streamlit as st
import os
import sys
import gc
import pandas as pd 
import duckdb 
from datetime import datetime, date 

st.set_page_config(page_title="Debug Data Export", page_icon="🔧", layout="wide")

st.title("🔧 Debug Data Export")
st.write("This is a simplified version to help debug the 'Prepare for Download' issue.")

# Add parent directory to sys.path
try:
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.abspath(os.path.join(current_file_dir, '..'))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    st.success("✅ Path setup successful")
except Exception as e:
    st.error(f"❌ Path setup failed: {e}")
    st.stop()

# Import utilities
try:
    from transfermarkt_datasets.core.asset import Asset 
    from transfermarkt_datasets.core.dataset import Dataset 
    from utils import load_td
    st.success("✅ Imports successful")
except Exception as e:
    st.error(f"❌ Import failed: {e}")
    st.stop()

# Load dataset
try:
    td = load_td()
    st.success(f"✅ Dataset loaded with {len(td.assets)} assets")
    st.write("Available assets:", list(td.assets.keys()))
except Exception as e:
    st.error(f"❌ Dataset loading failed: {e}")
    st.stop()

# Simple asset selection
asset_names = list(td.assets.keys())
selected_asset_name = st.selectbox("Select dataset for testing:", asset_names)
asset = td.assets[selected_asset_name]

# Check file path
def get_asset_prep_path(asset_obj):
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../'))
    if os.path.isabs(asset_obj.prep_path):
        return asset_obj.prep_path
    return os.path.join(PROJECT_ROOT, asset_obj.prep_path)

file_path = get_asset_prep_path(asset)
st.write(f"**File path:** {file_path}")
st.write(f"**File exists:** {os.path.exists(file_path)}")

if os.path.exists(file_path):
    try:
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        st.write(f"**File size:** {file_size_mb:.1f} MB")
    except Exception as e:
        st.write(f"**File size check failed:** {e}")

# Test basic DuckDB query
if st.button("Test Basic Query"):
    if not os.path.exists(file_path):
        st.error(f"File not found: {file_path}")
    else:
        try:
            with st.spinner("Testing basic query..."):
                con = duckdb.connect(database=':memory:', read_only=False)
                
                # Test 1: Basic file read
                st.write("**Test 1: Basic file read**")
                test_query = f"SELECT COUNT(*) as row_count FROM read_csv_auto('{str(file_path)}')"
                result = con.execute(test_query).fetchdf()
                total_rows = result['row_count'].iloc[0]
                st.success(f"✅ Total rows: {total_rows:,}")
                
                # Test 2: Sample data
                st.write("**Test 2: Sample data (first 5 rows)**")
                sample_query = f"SELECT * FROM read_csv_auto('{str(file_path)}') LIMIT 5"
                sample_df = con.execute(sample_query).fetchdf()
                st.dataframe(sample_df)
                
                # Test 3: Column info
                st.write("**Test 3: Column information**")
                st.write(f"Columns ({len(sample_df.columns)}): {list(sample_df.columns)}")
                
                con.close()
                
        except Exception as e:
            st.error(f"❌ Query failed: {str(e)}")
            st.code(f"Error details: {repr(e)}")

# Test Excel creation
if st.button("Test Excel Creation (Small Sample)"):
    if not os.path.exists(file_path):
        st.error(f"File not found: {file_path}")
    else:
        try:
            with st.spinner("Testing Excel creation..."):
                con = duckdb.connect(database=':memory:', read_only=False)
                
                # Get small sample
                sample_query = f"SELECT * FROM read_csv_auto('{str(file_path)}') LIMIT 100"
                sample_df = con.execute(sample_query).fetchdf()
                con.close()
                
                st.write(f"Sample data: {len(sample_df)} rows × {len(sample_df.columns)} columns")
                
                # Test Excel creation
                from io import BytesIO
                output = BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    sample_df.to_excel(writer, index=False, sheet_name='Data')
                
                excel_bytes = output.getvalue()
                excel_size_mb = len(excel_bytes) / (1024 * 1024)
                
                st.success(f"✅ Excel file created successfully ({excel_size_mb:.3f} MB)")
                
                # Offer download
                st.download_button(
                    label=f"📥 Download Test Excel ({excel_size_mb:.3f} MB)",
                    data=excel_bytes,
                    file_name=f"test_{selected_asset_name}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                
        except Exception as e:
            st.error(f"❌ Excel creation failed: {str(e)}")
            st.code(f"Error details: {repr(e)}")
            import traceback
            st.code(traceback.format_exc())

st.write("---")
st.write("**Instructions:**")
st.write("1. Select a dataset from the dropdown")
st.write("2. Click 'Test Basic Query' to verify data can be read")
st.write("3. Click 'Test Excel Creation' to verify Excel export works")
st.write("4. If both work, the issue might be in the full app's filtering logic")
