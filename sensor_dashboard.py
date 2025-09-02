import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json
import time
from urllib.parse import unquote_plus
import re

# Page config
st.set_page_config(
    page_title="🌱 Moisture Sensor Dashboard",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for styling
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(45deg, #2c3e50, #3498db);
        color: white;
        padding: 2rem;
        border-radius: 10px;
        text-align: center;
        margin-bottom: 2rem;
    }

    .metric-card {
        background: white;
        padding: 1rem;
        border-radius: 10px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        border-left: 4px solid #007bff;
    }

    .warning-card {
        border-left-color: #ffc107 !important;
        background: linear-gradient(135deg, #fff9e6 0%, #ffffff 100%);
    }

    .danger-card {
        border-left-color: #dc3545 !important;
        background: linear-gradient(135deg, #ffeaea 0%, #ffffff 100%);
    }

    .notification {
        padding: 1rem;
        border-radius: 8px;
        margin: 1rem 0;
        border-left: 4px solid;
    }

    .notification-success {
        background: #d4edda;
        color: #155724;
        border-left-color: #28a745;
    }

    .notification-warning {
        background: #fff3cd;
        color: #856404;
        border-left-color: #ffc107;
    }

    .notification-danger {
        background: #f8d7da;
        color: #721c24;
        border-left-color: #dc3545;
    }

    .stMetric {
        background: white;
        padding: 1rem;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'last_data' not in st.session_state:
    st.session_state.last_data = None
if 'last_update' not in st.session_state:
    st.session_state.last_update = None

# Channel presets
CHANNEL_PRESETS = {
    "Moisture Sensor 1": {
        "channel_id": st.secrets["thingspeak"]["sensor1_id"],
        "api_key": st.secrets["thingspeak"]["sensor1_key"]
    },
    "Moisture Sensor 2": {
        "channel_id": st.secrets["thingspeak"]["sensor2_id"],
        "api_key": st.secrets["thingspeak"]["sensor2_key"]
    },
    "Weather Station": {
        "channel_id": st.secrets["thingspeak"]["weather_id"],
        "api_key": st.secrets["thingspeak"]["weather_key"]
    },
    "Custom": {
        "channel_id": "",
        "api_key": ""
    }
}

def fetch_thingspeak_data(channel_id, api_key="", results=50):
    """Fetch data from ThingSpeak API"""
    url = f"https://api.thingspeak.com/channels/{channel_id}/feeds.json?results={results}"
    if api_key:
        url += f"&api_key={api_key}"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching data: {str(e)}")
        return None


def process_data(data):
    """Process ThingSpeak data into pandas DataFrame"""
    if not data or 'feeds' not in data or not data['feeds']:
        return None

    feeds = data['feeds']
    df = pd.DataFrame(feeds)

    # Convert timestamp
    df['created_at'] = pd.to_datetime(df['created_at'])

    # Convert fields to numeric where possible
    for field in ['field1', 'field2', 'field3', 'field4', 'field5', 'field6', 'field7']:
        if field in df.columns:
            df[field] = pd.to_numeric(df[field], errors='coerce')

    # Decode field8 messages
    if 'field8' in df.columns:
        df['field8'] = df['field8'].apply(lambda x: unquote_plus(x.replace('+', ' ')) if pd.notna(x) else '')

    return df


def check_missed_updates(df, expected_interval_hours=3):
    """Check for missed updates and return notification info"""
    if df is None or df.empty:
        return "danger", "No data available"

    latest_update = df['created_at'].max()
    now = datetime.now(latest_update.tz) if latest_update.tz else datetime.now()
    time_since_update = (now - latest_update).total_seconds() / 3600  # hours

    warning_threshold = expected_interval_hours + 0.5
    missed_threshold = expected_interval_hours * 2

    if time_since_update >= missed_threshold:
        return "danger", f"🚨 MISSED UPDATE! Last update was {time_since_update:.1f} hours ago (expected every {expected_interval_hours}h)"
    elif time_since_update >= warning_threshold:
        return "warning", f"⚠️ Update Overdue: {time_since_update:.1f} hours ago (next expected soon)"
    else:
        next_expected = expected_interval_hours - time_since_update
        return "success", f"✅ Status Normal: Last update {time_since_update:.1f}h ago (next in {next_expected:.1f}h)"


def extract_signal_strength(message):
    """Extract WiFi signal strength from log message"""
    if pd.isna(message):
        return None
    match = re.search(r'Signal:\s*(-?\d+)\s*dBm', str(message))
    return int(match.group(1)) if match else None


def get_status_text(status_code):
    """Convert status code to readable text"""
    if pd.isna(status_code):
        return "Unknown"

    status_map = {
        1: '🔄 Upload Retry Success',
        2: '📶 WiFi Retry Success',
        3: '🔋 Low Battery Warning',
        4: '✅ Normal Reading'
    }
    return status_map.get(int(status_code), f'Code: {int(status_code)}')


def main():
    # Header
    st.markdown("""
    <div class="main-header">
        <h1>🌱 Moisture Sensor Dashboard</h1>
        <p>Real-time monitoring and log viewer</p>
    </div>
    """, unsafe_allow_html=True)

    # Sidebar controls
    with st.sidebar:
        st.header("⚙️ Configuration")

        # Channel selection
        selected_preset = st.selectbox(
            "Select Channel Preset:",
            list(CHANNEL_PRESETS.keys()),
            index=0
        )

        # Get preset values
        preset = CHANNEL_PRESETS[selected_preset]

        # Channel ID input (safe to show)
        channel_id = st.text_input(
            "Channel ID:",
            value=preset['channel_id'],
            help="ThingSpeak Channel ID"
        )

        # Determine if using secret
        using_secret_key = preset['api_key'] != ""

        # API Key input
        api_key_input = st.text_input(
            "Read API Key:",
            value="hidden" if using_secret_key else "",  # show placeholder if secret exists
            type="password",
            help="Optional: enter a new key for private channels"
        )

        # If user typed a new key, use it; otherwise, use secret
        if api_key_input != "" and api_key_input != "hidden":
            api_key = api_key_input
        else:
            api_key = preset['api_key']

        # Results count
        results = st.selectbox(
            "Number of Results:",
            [10, 20, 50, 100, 200],
            index=1
        )

        # Auto-refresh
        auto_refresh = st.checkbox("Auto-refresh (30s)", value=False)

        # Refresh button
        if st.button("🔄 Refresh Data", type="primary") or auto_refresh:
            if channel_id:
                with st.spinner("Fetching data..."):
                    data = fetch_thingspeak_data(channel_id, api_key, results)
                    if data:
                        df = process_data(data)
                        st.session_state.last_data = df
                        st.session_state.last_update = datetime.now()
                        st.success(f"✅ Loaded {len(df) if df is not None else 0} entries")
                        if auto_refresh:
                            time.sleep(30)
                            st.experimental_rerun()
                    else:
                        st.error("❌ Failed to fetch data")
            else:
                st.warning("Please enter a Channel ID")

    # Main content
    if st.session_state.last_data is not None and not st.session_state.last_data.empty:
        df = st.session_state.last_data

        # Check for missed updates
        notification_type, notification_msg = check_missed_updates(df)

        # Display notification
        st.markdown(f"""
        <div class="notification notification-{notification_type}">
            {notification_msg}
        </div>
        """, unsafe_allow_html=True)

        # Statistics cards
        st.header("📊 Current Statistics")

        # Calculate stats
        latest = df.iloc[-1]
        moisture_values = df['field1'].dropna()
        battery_values = df['field3'].dropna()
        retry_count = len(df[(df['field4'] == 1) | (df['field4'] == 2)])

        # Create metrics row
        col1, col2, col3, col4, col5 = st.columns(5)

        with col1:
            current_moisture = latest['field1'] if pd.notna(latest['field1']) else 0
            st.metric(
                "Current Moisture",
                f"{current_moisture:.1f}%",
                help="Latest moisture reading"
            )

        with col2:
            current_battery = latest['field3'] if pd.notna(latest['field3']) else 0
            battery_color = "normal"
            if current_battery < 3.3:
                battery_color = "inverse"
            st.metric(
                "Battery Voltage",
                f"{current_battery:.2f}V",
                help="Current battery level"
            )

        with col3:
            avg_moisture = moisture_values.mean() if len(moisture_values) > 0 else 0
            st.metric(
                "Average Moisture",
                f"{avg_moisture:.1f}%",
                help="Average across all readings"
            )

        with col4:
            st.metric(
                "Retry Attempts",
                retry_count,
                help="Number of retry attempts"
            )

        with col5:
            st.metric(
                "Total Readings",
                len(df),
                help="Total number of data points"
            )

        # Charts section
        st.header("📈 Data Visualization")

        # Create two columns for charts
        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            # Moisture chart
            fig_moisture = px.line(
                df,
                x='created_at',
                y='field1',
                title='💧 Moisture Level Over Time',
                labels={'field1': 'Moisture (%)', 'created_at': 'Time'}
            )
            fig_moisture.update_traces(line_color='#28a745', fill='tonexty')
            fig_moisture.update_layout(yaxis_range=[0, 100])
            st.plotly_chart(fig_moisture, width='stretch')

            # ADC Values
            fig_adc = px.line(
                df,
                x='created_at',
                y='field2',
                title='⚡ Raw ADC Values',
                labels={'field2': 'ADC Value', 'created_at': 'Time'}
            )
            fig_adc.update_traces(line_color='#17a2b8')
            st.plotly_chart(fig_adc, width='stretch')

        with chart_col2:
            # Battery chart
            fig_battery = px.line(
                df,
                x='created_at',
                y='field3',
                title='🔋 Battery Voltage',
                labels={'field3': 'Voltage (V)', 'created_at': 'Time'}
            )
            fig_battery.update_traces(line_color='#ffc107')
            # Add low battery warning line
            fig_battery.add_hline(y=3.3, line_dash="dash", line_color="red",
                                  annotation_text="Low Battery Warning")
            st.plotly_chart(fig_battery, width='stretch')

            # WiFi Signal Strength (if available)
            df['signal_strength'] = df['field8'].apply(extract_signal_strength)
            signal_data = df.dropna(subset=['signal_strength'])

            if not signal_data.empty:
                fig_signal = px.line(
                    signal_data,
                    x='created_at',
                    y='signal_strength',
                    title='📶 WiFi Signal Strength',
                    labels={'signal_strength': 'Signal (dBm)', 'created_at': 'Time'}
                )
                fig_signal.update_traces(line_color='#6f42c1')
                fig_signal.update_layout(yaxis_range=[-90, -40])
                st.plotly_chart(fig_signal, width='stretch')

        # Connection attempts chart
        st.subheader("🔄 Connection Attempts")

        # Calculate attempts based on status codes
        df['attempts'] = df['field4'].apply(lambda x: 2 if x in [1, 2] else 1 if pd.notna(x) else 1)
        df['status_color'] = df['field4'].apply(lambda x: 'red' if x in [1, 2] else 'green' if pd.notna(x) else 'blue')

        fig_attempts = px.bar(
            df,
            x='created_at',
            y='attempts',
            title='Connection Attempts Over Time',
            labels={'attempts': 'Number of Attempts', 'created_at': 'Time'},
            color='status_color',
            color_discrete_map={'red': '#dc3545', 'green': '#28a745', 'blue': '#007bff'}
        )
        fig_attempts.update_layout(yaxis_range=[0, 3], showlegend=False)
        st.plotly_chart(fig_attempts, width='stretch')

        # Data table
        st.header("📋 Recent Readings")

        # Prepare display dataframe
        display_df = df.copy()
        display_df['Time'] = display_df['created_at'].dt.strftime('%Y-%m-%d %H:%M:%S')
        display_df['Moisture (%)'] = display_df['field1']
        display_df['ADC Value'] = display_df['field2']
        display_df['Battery (V)'] = display_df['field3']
        display_df['Status'] = display_df['field4'].apply(get_status_text)
        display_df['Log Message'] = display_df['field8'].fillna('')

        # Show last 20 entries
        columns_to_show = ['Time', 'Moisture (%)', 'ADC Value', 'Battery (V)', 'Status', 'Log Message']
        st.dataframe(
            display_df[columns_to_show].tail(20).iloc[::-1],  # Reverse to show newest first
            width='stretch',
            hide_index=True
        )

        # Download data
        st.header("💾 Export Data")
        csv = df.to_csv(index=False)
        st.download_button(
            label="📥 Download as CSV",
            data=csv,
            file_name=f"moisture_data_{channel_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )

    else:
        st.info("👆 Please select a channel and click 'Refresh Data' to load sensor data")

        # Show sample of what the dashboard looks like
        st.markdown("""
        ### 🌟 Features:
        - **Real-time monitoring** of moisture sensors
        - **Missed update notifications** (alerts when sensors don't report within expected 3-hour intervals)
        - **Interactive charts** for moisture, battery, and signal strength
        - **Connection retry tracking** to monitor sensor reliability
        - **Data export** to CSV format
        - **Auto-refresh** capability for continuous monitoring

        ### 🚀 Getting Started:
        1. Select a preset channel or enter a custom Channel ID
        2. Optionally enter your Read API Key for private channels
        3. Click "Refresh Data" to load the latest readings
        4. Enable auto-refresh for continuous monitoring
        """)

    # Footer
    st.markdown("---")
    st.markdown(
        "🌱 **Moisture Sensor Dashboard** | "
        f"Last updated: {st.session_state.last_update.strftime('%Y-%m-%d %H:%M:%S') if st.session_state.last_update else 'Never'}"
    )


if __name__ == "__main__":
    main()