
import streamlit as st
import sys
import os

# Ensure Agent.py is importable
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from Agent import pop_sector_upgrade_agent
except ImportError:
    st.error("Could not import 'pop_sector_upgrade_agent' from Agent.py. Ensure Agent.py is in the same directory.")
    st.stop()

# Page config
st.set_page_config(page_title="IndiGo Flight Upgrade Assistant", page_icon="✈️", layout="wide")


def display_upgrade_result(result):
    """Render upgrade options without markdown/HTML."""
    # Handle the nested structure from pop_sector_upgrade_agent
    upgrade_options = []
    print(result)
    if isinstance(result, dict) and "results" in result:
        upgrade_options = result["results"]
    elif isinstance(result, list):
        upgrade_options = result
    
    if upgrade_options:
        st.subheader("Available Upgrade Options")
        for i, opt in enumerate(upgrade_options, 1):
            bundle = opt.get("bundle", {})
            seats = bundle.get("seat", [])

            # Extract first seat designator
            seat_display = "N/A"
            if seats and len(seats) > 0:
                first_seat = seats[0]
                if isinstance(first_seat, dict):
                    seat_display = first_seat.get("designator") or first_seat.get("unitKey", "N/A")

            # Display option
            st.write(f"**Option {i}**")
            st.write("**Sector:**", bundle.get("sector", "N/A"))
            st.write("**Seat:**", seat_display)
            st.write("**Price:**", f"₹{bundle.get('price', 0):,}")
            st.divider()
    else:
        st.info("No upgrade options available at this time.")
        
def main():
    st.title("IndiGo Flight Upgrade Assistant")

    # Sidebar inputs only
    with st.sidebar:
        pnr = st.text_input("PNR / Record Locator *", placeholder="6-character PNR", max_chars=6).upper()
        last_name = st.text_input("Last Name *", placeholder="Passenger last name").upper()
        email = st.text_input("Email Address", placeholder="customer@email.com")
        mobile = st.text_input("Mobile Number", placeholder="10-digit mobile number", max_chars=10)

        valid_input = bool(len(pnr) == 6 and last_name)
        check_upgrade = st.button("Check Upgrade Availability", disabled=not valid_input, use_container_width=True)
        if not valid_input:
            st.caption("PNR and Last Name are required.")

    # Main area
    if check_upgrade:
        with st.spinner("Checking upgrade availability..."):
            try:
                kwargs = {"pnr": pnr, "last_name": last_name}
                if email:
                    kwargs["email"] = email
                if mobile:
                    kwargs["mobile"] = mobile

                result = pop_sector_upgrade_agent(**kwargs)
                st.session_state.upgrade_result = result
            except Exception as e:
                st.error(f"Error occurred: {e}")
                st.exception(e)
                return
        st.success("Search completed!")

    if "upgrade_result" in st.session_state:
        display_upgrade_result(st.session_state.upgrade_result)


if __name__ == "__main__":
    main()
