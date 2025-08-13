# app.py
# AI Listing Writer – Local Streamlit app (no MLS; features inside a FORM so dropdowns don't close)
# - Fixed model: gpt-4.1-mini
# - Grouped feature selectors (no search bar)
# - Auto-generates: Upgrades/Features bullets + SEO keywords from selections (+ optional extras)
# - Robust JSON handling + self-repair for missing fields
# - Character range enforcement for MLS description
# Run: streamlit run app.py

import json
import os
import re
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

# ---------- Setup (cloud + local) ----------

load_dotenv()  # lets local .env work

# Read from Streamlit Secrets first (cloud), then .env (local)
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
APP_PASSWORD   = st.secrets.get("APP_PASSWORD")   or os.getenv("APP_PASSWORD")

st.set_page_config(page_title="AI Listing Writer (Beta)", page_icon="🏠", layout="wide")

if not OPENAI_API_KEY:
    st.error("Missing OPENAI_API_KEY (set it in Streamlit → Settings → Secrets, or your local .env).")
    st.stop()

# ---- Tiny password gate (beta) ----
def check_password():
    # already authenticated?
    if st.session_state.get("authed"):
        with st.sidebar:
            if st.button("Log out"):
                st.session_state["authed"] = False
                st.rerun()
        return True

    st.title("AI Listing Writer — Beta Access")
    pw = st.text_input("Enter beta password", type="password")
    if st.button("Enter"):
        if APP_PASSWORD and pw == APP_PASSWORD:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Incorrect password")
    st.stop()

# gate the app
if not check_password():
    st.stop()

# OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# ---------- Model ----------
MODEL_NAME = "gpt-4.1-mini"  # change to "gpt-4o-mini" if you prefer

# ---------- Data model ----------
@dataclass
class ListingInput:
    address: str
    city: str
    state: str
    zip_code: str
    beds: Optional[float]
    baths: Optional[float]
    sqft: Optional[int]
    lot_size: Optional[int]
    year_built: Optional[int]
    property_type: str
    price: Optional[int]
    # Derived from selections:
    keywords: List[str]
    upgrades_bullets: str
    # Free text:
    neighborhood_notes: str
    target_buyer_profile: str
    tone: str
    mls_char_limit: int
    detail_level: str  # "Concise", "Standard", "Descriptive"
    highlight_features: List[str]  # prioritized features to emphasize

# ---------- Feature Taxonomy ----------
def feature_taxonomy() -> Dict[str, List[Tuple[str, List[str]]]]:
    return {
        "Exterior & Lot": [
            ("Corner lot", ["corner lot"]),
            ("Cul-de-sac", ["cul-de-sac"]),
            ("Large backyard", ["large backyard", "spacious yard", "big yard"]),
            ("Usable yard", ["usable yard", "flat yard"]),
            ("Drought-tolerant landscaping", ["drought tolerant", "low maintenance landscaping"]),
            ("Mature trees", ["mature trees"]),
            ("Fruit trees", ["fruit trees"]),
            ("Garden beds", ["garden beds"]),
            ("RV/Boat parking", ["rv parking", "boat parking"]),
            ("Gated driveway", ["gated driveway"]),
            ("Circular driveway", ["circular driveway"]),
            ("Motor court", ["motor court"]),
            ("Privacy fencing", ["privacy fencing"]),
            ("Privacy hedges", ["privacy hedges"]),
            # Garage sizes & details
            ("1-car garage", ["1-car garage", "single car garage"]),
            ("2-car garage", ["2-car garage", "two car garage"]),
            ("3-car garage", ["3-car garage", "three car garage"]),
            ("4-car garage", ["4-car garage", "four car garage"]),
            ("5-car+ garage", ["5-car garage", "five car garage"]),
            ("Tandem garage", ["tandem garage"]),
            ("Detached garage", ["detached garage"]),
            ("Workshop area", ["garage workshop", "workbench"]),
            ("Built-in garage storage", ["garage storage", "built-in garage cabinets"]),
            ("EV charger (Level 2)", ["ev charger", "240v outlet"]),
        ],
        "Outdoor Living": [
            ("Covered patio", ["covered patio"]),
            ("Pergola", ["pergola"]),
            ("Gazebo", ["gazebo"]),
            ("Retractable awning", ["retractable awning"]),
            ("Deck (wood)", ["wood deck"]),
            ("Deck (composite)", ["composite deck"]),
            ("Rooftop deck", ["rooftop deck"]),
            ("Wraparound porch", ["wraparound porch"]),
            ("Balcony", ["balcony"]),
            ("Built-in BBQ", ["built-in bbq"]),
            ("Outdoor kitchen (sink/fridge)", ["outdoor kitchen", "outdoor sink", "outdoor fridge"]),
            ("Bar seating", ["bar seating"]),
            ("Fire pit", ["fire pit"]),
            ("Outdoor fireplace", ["outdoor fireplace"]),
            ("Water feature (fountain/pond/waterfall)", ["water feature", "fountain", "pond", "waterfall"]),
            ("Putting green", ["putting green"]),
            ("Sport court", ["sport court"]),
            ("Pickleball", ["pickleball"]),
            ("Play structure", ["play structure"]),
            ("Dog run", ["dog run"]),
            # Pool / spa / sauna
            ("Pool (in-ground)", ["pool", "in-ground pool"]),
            ("Pool (saltwater)", ["saltwater pool"]),
            ("Pool (heated)", ["heated pool"]),
            ("Lap pool", ["lap pool"]),
            ("Spa/Hot tub", ["spa", "hot tub"]),
            ("Sauna (dry)", ["dry sauna"]),
            ("Sauna (infrared)", ["infrared sauna"]),
        ],
        "Views & Orientation": [
            ("Ocean view", ["ocean view"]),
            ("Bay view", ["bay view"]),
            ("City lights view", ["city lights view"]),
            ("Mountain view", ["mountain view"]),
            ("Canyon/Greenbelt view", ["canyon view", "greenbelt view"]),
            ("Golf course view", ["golf course view"]),
            ("Park view", ["park view"]),
            ("East-facing (morning light)", ["east-facing"]),
            ("West-facing (sunsets)", ["west-facing"]),
            ("South-facing yard", ["south-facing yard"]),
            ("Picture windows", ["picture windows"]),
            ("Bay window", ["bay window"]),
        ],
        "Property Type & Layout": [
            ("Single-story (step-free)", ["single story", "single level", "step-free"]),
            ("Two-story", ["two story"]),
            ("Split-level", ["split level"]),
            ("Open-concept", ["open concept", "open floor plan"]),
            ("Great room", ["great room"]),
            ("Vaulted ceilings", ["vaulted ceilings"]),
            ("Double-height ceilings", ["double-height ceilings"]),
            ("Skylights", ["skylights"]),
            ("Formal dining", ["formal dining"]),
            ("Den/Home office", ["den", "home office"]),
            ("Loft", ["loft"]),
            ("Media room/Home theater", ["media room", "home theater"]),
            ("Game room", ["game room"]),
            ("Gym", ["home gym"]),
            ("Mudroom", ["mudroom"]),
            ("ADU (permitted)", ["adu"]),
            ("Guest house/Casita (permitted)", ["guest house", "casita"]),
            ("Primary suite on main", ["primary on main"]),
            ("Dual primary suites", ["dual primary"]),
            ("Jack-and-Jill bath", ["jack and jill"]),
            ("En-suite secondaries", ["en-suite bedrooms"]),
            ("Built-ins", ["built-ins"]),
            ("Window seats", ["window seats"]),
            ("Wainscoting/Trim/Crown", ["wainscoting", "crown molding", "trim work"]),
            ("Recessed lighting", ["recessed lighting"]),
            ("Statement lighting", ["statement lighting"]),
            ("Fireplace(s)", ["fireplace"]),
        ],
        "Kitchen": [
            ("Newly updated kitchen", ["updated kitchen", "renovated kitchen"]),
            ("Quartz countertops", ["quartz countertops"]),
            ("Granite countertops", ["granite countertops"]),
            ("Quartzite countertops", ["quartzite"]),
            ("Marble countertops", ["marble"]),
            ("Butcher block counters", ["butcher block"]),
            ("Soft-close cabinets", ["soft close cabinets"]),
            ("Walk-in pantry", ["walk-in pantry"]),
            ("Glass uppers", ["glass uppers"]),
            ("Custom millwork", ["custom cabinets"]),
            ("Island with seating", ["kitchen island with seating"]),
            ("Waterfall edge", ["waterfall island"]),
            ("Prep sink", ["prep sink"]),
            ("Stainless appliances", ["stainless steel appliances"]),
            ("Panel-ready/built-in fridge", ["panel ready appliances", "built-in fridge"]),
            ("Gas range", ["gas range"]),
            ("Professional range (36\")", ["36-inch range", "professional range"]),
            ("Professional range (48\")", ["48-inch range", "professional range"]),
            ("Double oven", ["double oven"]),
            ("Convection/steam oven", ["convection oven", "steam oven"]),
            ("Pot filler", ["pot filler"]),
            ("Vented hood", ["vented hood"]),
            ("Farmhouse sink", ["farmhouse sink"]),
            ("Touch faucet", ["touch faucet"]),
            ("Water filtration/RO", ["water filtration", "reverse osmosis"]),
            ("Beverage center/coffee bar", ["beverage center", "coffee bar"]),
            ("Wine fridge", ["wine fridge"]),
            ("Microwave drawer", ["microwave drawer"]),
            ("Designer backsplash", ["designer backsplash"]),
        ],
        "Bathrooms": [
            ("Double vanity", ["double vanity"]),
            ("Soaking tub", ["soaking tub"]),
            ("Separate shower", ["separate shower"]),
            ("Walk-in/curbless shower", ["walk-in shower", "curbless shower"]),
            ("Rain shower", ["rain shower"]),
            ("Body sprays", ["body sprays"]),
            ("Frameless glass", ["frameless glass"]),
            ("Heated floors", ["heated floors"]),
            ("Towel warmer", ["towel warmer"]),
            ("Bidet/bidet seat", ["bidet", "bidet seat"]),
            ("Smart mirror", ["smart mirror", "backlit mirror"]),
            ("Smart lighting (bath)", ["smart bath lighting"]),
            ("Linen closet", ["linen closet"]),
            ("Updated powder room", ["updated powder room"]),
            ("Skylight in bath", ["bath skylight"]),
        ],
        "Bedrooms & Storage": [
            ("Primary walk-in closet", ["walk-in closet"]),
            ("Custom closet system", ["custom closets"]),
            ("Primary balcony", ["primary balcony"]),
            ("Primary retreat/sitting area", ["primary retreat"]),
            ("Fireplace in primary", ["primary fireplace"]),
            ("Large secondary bedrooms", ["large secondary bedrooms"]),
            ("Guest suite", ["guest suite"]),
            ("Nursery", ["nursery"]),
            ("Coat closet", ["coat closet"]),
            ("Linen storage", ["linen storage"]),
            ("Attic storage", ["attic storage"]),
            ("Shed/Outbuilding", ["storage shed", "outbuilding"]),
            ("Overhead garage racks", ["garage racks"]),
        ],
        "Laundry & Utility": [
            ("Inside laundry room", ["laundry room"]),
            ("Garage laundry", ["garage laundry"]),
            ("Closet laundry", ["closet laundry"]),
            ("Laundry sink", ["laundry sink"]),
            ("Folding counter", ["folding counter"]),
            ("Laundry cabinetry", ["laundry cabinets"]),
            ("Hanging rack", ["hanging rack"]),
            ("Gas hookups", ["gas hookups"]),
            ("Electric hookups (220V)", ["electric hookups", "220v laundry"]),
        ],
        "Flooring & Surfaces": [
            ("Hardwood/Wood floors", ["hardwood floors", "wood floors"]),
            ("Luxury vinyl plank (LVP)", ["lvp flooring"]),
            ("Tile (porcelain/ceramic)", ["tile floors"]),
            ("Stone (travertine/marble/slate)", ["stone floors", "travertine", "marble", "slate"]),
            ("Polished concrete", ["polished concrete"]),
            ("New carpet", ["new carpet"]),
            ("Hypoallergenic flooring", ["hypoallergenic flooring"]),
        ],
        "Systems, Energy & Smart Home": [
            ("Solar (owned)", ["owned solar"]),
            ("Solar (leased)", ["leased solar"]),
            ("Battery backup", ["battery backup"]),
            ("Generator transfer switch", ["generator transfer switch"]),
            ("Dual-pane windows", ["dual pane windows"]),
            ("Energy-efficient glazing", ["energy efficient windows"]),
            ("Upgraded insulation (attic/crawl)", ["attic insulation", "crawlspace insulation"]),
            ("Tankless water heater", ["tankless water heater"]),
            ("Newer HVAC", ["newer hvac"]),
            ("Multi-zone HVAC", ["multi-zone hvac"]),
            ("Whole-house fan", ["whole house fan"]),
            ("Smart thermostat", ["smart thermostat"]),
            ("Video doorbell", ["video doorbell"]),
            ("Security cameras", ["security cameras"]),
            ("Smart locks", ["smart locks"]),
            ("Smart lighting", ["smart lighting"]),
            ("Wired Ethernet (CAT6)", ["cat6 wiring", "ethernet wiring"]),
            ("Speaker pre-wire", ["speaker prewire"]),
            ("Security system", ["security system"]),
            ("Interior fire sprinklers", ["fire sprinklers"]),
            ("Smart smoke detectors", ["smart smoke detectors"]),
            ("Smart CO detectors", ["smart co detectors"]),
            ("Fresh-air system/ERV", ["erv", "fresh air system"]),
            ("Air purifier", ["air purifier"]),
            ("Low-VOC finishes", ["low voc finishes"]),
        ],
        "Community & HOA": [
            ("Gated community", ["gated community"]),
            ("Guard-gated community", ["guard gated"]),
            ("Community pool", ["community pool"]),
            ("Community spa", ["community spa"]),
            ("Clubhouse", ["clubhouse"]),
            ("Gym/Fitness center", ["fitness center"]),
            ("Pickleball courts", ["pickleball"]),
            ("Tennis courts", ["tennis courts"]),
            ("Playground", ["playground"]),
            ("Dog park", ["dog park"]),
            ("Walking trails", ["walking trails"]),
            ("Community garden", ["community garden"]),
            ("Package lockers", ["package lockers"]),
            ("Community RV lot", ["community rv lot"]),
        ],
        "Location & Access": [
            ("Near parks", ["near parks"]),
            ("Near trails", ["near trails"]),
            ("Near shopping", ["near shopping"]),
            ("Near dining", ["near dining"]),
            ("Near hospitals/medical", ["near hospitals", "near medical"]),
            ("Easy freeway access", ["easy freeway access"]),
            ("Near I-5", ["near i-5"]),
            ("Near I-15", ["near i-15"]),
            ("Near local schools (proximity)", ["near local schools"]),
            ("Transit nearby", ["near transit"]),
        ],
        "Specialty / Market Segments": [
            ("Accessibility: zero-step entry", ["zero step entry", "step-free"]),
            ("Accessibility: wide halls/doors", ["wide hallways", "wide doors"]),
            ("Roll-in/curbless shower", ["roll-in shower", "curbless shower"]),
            ("New construction/recent build", ["new construction", "recent build"]),
            ("Craftsman style", ["craftsman"]),
            ("Spanish/Mediterranean style", ["spanish", "mediterranean"]),
            ("Mid-Century style", ["mid-century"]),
            ("Modern/Contemporary", ["modern", "contemporary"]),
            ("Farmhouse/Tudor", ["farmhouse", "tudor"]),
            ("Income/ADU/lock-off", ["adu potential", "separate entrance", "lock off"]),
            ("Well", ["well"]),
            ("Septic (updated)", ["septic updated"]),
            ("Workshop/Barn/Studio", ["workshop", "barn", "artist studio"]),
        ],
    }

HEADLINE_DEFAULTS = [
    "Pool (in-ground)", "Spa/Hot tub", "Ocean view", "Mountain view",
    "Large backyard", "Open-concept", "ADU (permitted)", "Guest house/Casita (permitted)",
    "Solar (owned)", "Single-story (step-free)", "2-car garage", "3-car garage", "4-car garage"
]

# ---------- Keyword & Upgrades builders ----------
def build_keywords_from_selections(
    selected: Dict[str, List[str]],
    beds: Optional[float],
    baths: Optional[float],
    sqft: Optional[int],
    lot_size: Optional[int],
    year_built: Optional[int],
    property_type: str,
    extra_keywords: List[str]
) -> List[str]:
    tax = feature_taxonomy()
    tokens: List[str] = []
    label_to_variants: Dict[str, List[str]] = {
        label: variants for group, items in tax.items() for (label, variants) in items
    }

    for group, labels in selected.items():
        for label in labels:
            variants = label_to_variants.get(label, [])
            if variants:
                tokens.extend(variants)
            else:
                tokens.append(label)

    if beds:
        tokens.append(f"{int(beds)} bedrooms")
    if baths is not None:
        tokens.append(f"{baths} bathrooms")
    if sqft:
        tokens.append(f"{int(sqft)} sqft")
    if lot_size:
        tokens.append(f"{int(lot_size)} sf lot")
    if year_built:
        tokens.append(f"built {int(year_built)}")
    if property_type:
        tokens.append(property_type.lower())

    tokens.extend([k.strip() for k in extra_keywords if k.strip()])

    cleaned: List[str] = []
    seen = set()
    for t in tokens:
        t2 = " ".join(str(t).split()).strip(",; ").lower()
        if t2 and t2 not in seen:
            seen.add(t2)
            cleaned.append(t2)

    return cleaned[:60]

def build_upgrades_bullets(selected: Dict[str, List[str]], custom_lines: List[str]) -> str:
    lines: List[str] = []
    for group, labels in selected.items():
        if not labels:
            continue
        line = f"- {group}: " + ", ".join(labels)
        lines.append(line)
    for raw in custom_lines:
        val = " ".join(raw.split()).strip()
        if val:
            lines.append(f"- {val}")
    return "\n".join(lines[:30])

# ---------- Prompt + Model flow ----------
REQUIRED_KEYS = ["mls_description", "social_caption", "instagram_hashtags", "video_script_60s"]

def detail_level_guidance(level: str) -> str:
    if level == "Concise":
        return "Aim for the LOWER end of the allowed range. Use concise, information-dense sentences."
    if level == "Descriptive":
        return "Aim for the UPPER end of the allowed range. Add specific, factual details drawn from inputs."
    return "Aim for the MIDDLE of the allowed range with balanced specificity and clarity."

def build_primary_prompt(li: ListingInput) -> str:
    min_chars = int(li.mls_char_limit * 0.9)
    guidance = detail_level_guidance(li.detail_level)
    headline = ", ".join(li.highlight_features[:6]) if li.highlight_features else ""
    kw_text = ", ".join(li.keywords)

    return f"""
You are an expert real estate copywriter for MLS, Zillow/Redfin, and social media.
Write compelling, accurate, compliant copy. Avoid fair-housing issues and prohibited wording.

Return ONLY valid JSON with these keys:
- "mls_description": string (between {min_chars} and {li.mls_char_limit} characters, no emojis)
- "social_caption": string (1–2 sentences, approachable, no hashtags)
- "instagram_hashtags": string (10–18 space-separated hashtags, no commas)
- "video_script_60s": string (a 45–60 second walkthrough script; short sentences; easy to read aloud)

Context:
- Address: {li.address}, {li.city}, {li.state} {li.zip_code}
- Property Type: {li.property_type}
- Beds/Baths: {li.beds} bd / {li.baths} ba
- Interior Sq Ft: {li.sqft}
- Lot Size: {li.lot_size}
- Year Built: {li.year_built}
- Price: {li.price}
- SEO Keywords to weave in: {kw_text}
- Upgrades/Features (bulleted): 
{li.upgrades_bullets}
- Neighborhood notes (neutral proximity phrasing): {li.neighborhood_notes}
- Highlight features to emphasize early: {headline if headline else "None"}
- Target buyer profile: {li.target_buyer_profile}
- Tone: {li.tone}

Rules:
- MLS description MUST be between {min_chars} and {li.mls_char_limit} chars.
- {guidance}
- Emphasize the highlight features in the first 1–2 sentences if applicable.
- Use the upgrades/features and neighborhood notes to reach the target length—be specific and factual.
- No exaggerated claims; avoid steering; no terms implying a protected class.
- Replace subjective school/safety claims with neutral proximity phrasing (“near local schools,” “close to parks”).
- Plain language; avoid fluff/clichés; vary sentence length.
- For the video script: opening hook, 3–5 key features, 1 lifestyle/neighborhood beat, soft CTA (“Schedule a tour to see it in person.”). No phone numbers.

Output JSON example:
{{
  "mls_description": "…",
  "social_caption": "…",
  "instagram_hashtags": "#sandiegorealestate #listings …",
  "video_script_60s": "…"
}}
""".strip()

def safe_json_extract(text: str) -> Dict[str, Any]:
    text = text or ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end+1])
        raise

def chat_raw(system_prompt: str, user_prompt: str, temperature: float) -> str:
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "system", "content": system_prompt},
                  {"role": "user", "content": user_prompt}],
        temperature=temperature
    )
    return resp.choices[0].message.content or ""

def chat_json(system_prompt: str, user_prompt: str, temperature: float):
    raw = chat_raw(system_prompt, user_prompt, temperature)
    return safe_json_extract(raw), raw

def merge_preserving(original: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(original or {})
    for k, v in (updates or {}).items():
        out[k] = v
    return out

def validate_and_repair(li: ListingInput, data: Dict[str, Any]) -> Dict[str, Any]:
    system = "You are a meticulous, compliant real estate listing copywriter."
    min_chars = int(li.mls_char_limit * 0.9)

    missing = [k for k in REQUIRED_KEYS if not (isinstance(data.get(k), str) and data.get(k).strip())]
    if not missing:
        return data

    shared_ctx = f"""
Address: {li.address}, {li.city}, {li.state} {li.zip_code}
Type: {li.property_type}
Beds/Baths: {li.beds} bd / {li.baths} ba | Sq Ft: {li.sqft} | Lot: {li.lot_size} | Year: {li.year_built} | Price: {li.price}
Keywords: {", ".join(li.keywords)}
Upgrades (bulleted):
{li.upgrades_bullets}
Neighborhood: {li.neighborhood_notes}
Highlight features: {", ".join(li.highlight_features)}
Tone: {li.tone}
"""

    for key in missing:
        if key == "social_caption":
            prompt = f"""
Using this property context:
{shared_ctx}

Write ONLY JSON with:
{{"social_caption": "<1–2 sentence caption (no hashtags) in a friendly {li.tone.lower()} tone>"}}
"""
        elif key == "instagram_hashtags":
            prompt = f"""
Using this property context:
{shared_ctx}

Write ONLY JSON with:
{{"instagram_hashtags": "<10–18 space-separated Instagram hashtags, no commas>"}}
Prefer local + lifestyle + property-type tags. No emojis.
"""
        elif key == "video_script_60s":
            prompt = f"""
Using this property context:
{shared_ctx}

Write ONLY JSON with:
{{"video_script_60s": "<45–60 second walkthrough script. Hook, 3–5 key features, 1 lifestyle/neighborhood beat, soft CTA. No phone numbers.>"}}
Use short sentences that read well on camera.
"""
        elif key == "mls_description":
            prompt = f"""
Using this property context:
{shared_ctx}

Write ONLY JSON with:
{{"mls_description": "<MLS description between {min_chars} and {li.mls_char_limit} characters, no emojis>"}}
Be specific and compliant. Replace subjective school/safety claims with neutral proximity phrasing.
"""
        else:
            continue

        partial, _ = chat_json(system, prompt, temperature=0.45)
        data = merge_preserving(data, partial)

    return data

def ensure_length(li: ListingInput, data: Dict[str, Any]) -> Dict[str, Any]:
    min_chars = int(li.mls_char_limit * 0.9)
    max_chars = li.mls_char_limit
    current = (data.get("mls_description") or "").strip()

    if min_chars <= len(current) <= max_chars:
        return data

    system = "You are a meticulous, compliant real estate listing copywriter."
    prompt = f"""
Revise the following MLS description to be between {min_chars} and {max_chars} characters.
Keep meaning and compliance. Add concrete, factual property details where helpful.
Return ONLY JSON with this single key:
{{"mls_description": "…"}}

Current (length {len(current)}):
<<<{current}>>>
""".strip()

    revision_json, _ = chat_json(system, prompt, temperature=0.5 if li.detail_level != "Concise" else 0.35)
    revised_desc = (revision_json.get("mls_description") or "").strip()
    if revised_desc:
        data["mls_description"] = revised_desc
    return data

# ---------- UI ----------
st.title("🏠 AI Listing Writer")
st.caption("Check the features, and we’ll generate an MLS-ready description, a social caption, hashtags, and a 60-second video script.")

with st.sidebar:
    st.markdown("### Settings")
    detail_level = st.selectbox("Detail Level", ["Concise", "Standard", "Descriptive"], index=2)
    mls_char_limit = st.slider("MLS Character Limit", min_value=500, max_value=1800, value=1800, step=50)

# Precompute taxonomy/groups so they're available outside the form as well
tax = feature_taxonomy()
groups = list(tax.keys())

# Property basics
col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("Property Basics")
    address = st.text_input("Street Address*", "")
    city = st.text_input("City*", "")
    state = st.text_input("State*", "CA")
    zip_code = st.text_input("ZIP*", "")
    beds = st.number_input("Bedrooms", min_value=0.0, step=0.5, value=3.0)
    baths = st.number_input("Bathrooms", min_value=0.0, step=0.5, value=2.0)
    sqft = st.number_input("Interior Sq Ft", min_value=0, step=50, value=1600)
    lot_size = st.number_input("Lot Size (sq ft)", min_value=0, step=100, value=5000)
    year_built = st.number_input("Year Built", min_value=1800, max_value=2100, value=1995)
    price = st.number_input("List Price", min_value=0, step=5000, value=799000)
    property_type = st.selectbox("Property Type", ["Single Family", "Condo", "Townhome", "Multi-Unit", "Luxury", "Investment"])
    tone = st.selectbox("Tone", ["Professional", "Warm & Inviting", "Luxury", "Investor-Focused", "Coastal Vibes"])
    target_buyer_profile = st.text_input("Target Buyer Profile", "Move-up buyers who value indoor-outdoor living")
    neighborhood_notes = st.text_area("Neighborhood Notes (proximity phrasing only)", "Near parks and local schools; quick access to I-15; minutes to shops and cafes.")

# ---- Feature selectors in a FORM (no reruns until 'Apply') ----
with col_right:
    st.subheader("Features (check all that apply)")

with st.form("features_form", clear_on_submit=False):
    feat_cols = st.columns(2)

    def _group_key(idx: int) -> str:
        return f"sel_group_{idx}"

    # Collect what the user picked in this form run,
    # but DON'T write to session_state until Apply is clicked.
    new_selected_by_key: Dict[str, List[str]] = {}

    for i, group in enumerate(groups):
        all_labels = [label for (label, _v) in tax[group]]
        key = _group_key(i)
        current_selected = st.session_state.get(key, [])

        with feat_cols[i % 2]:
            with st.expander(group, expanded=False):
                new_visible = st.multiselect(
                    label=f"{group} features",
                    options=all_labels,
                    default=[x for x in current_selected if x in all_labels],
                    key=f"ui_{key}",
                    label_visibility="collapsed",
                    placeholder="Select one or more features"
                )
                # Just remember what the user picked for this group in this form run
                new_selected_by_key[key] = new_visible

    # Form button
    applied = st.form_submit_button("Apply feature selections")

    if applied:
        # NOW commit the changes — overwrite old selections with the new ones
        for key, new_list in new_selected_by_key.items():
            st.session_state[key] = new_list
        st.toast("Applied!", icon="✅")

# Assemble selection dict from session_state
selections: Dict[str, List[str]] = {group: [] for group in groups}
for i, group in enumerate(groups):
    selections[group] = st.session_state.get(f"sel_group_{i}", [])

# ---- Optional extra keywords (BEFORE generation) ----
st.session_state.setdefault("extra_keywords_raw", "")
extra_kw_raw = st.text_input("Additional Keywords and Features", key="extra_keywords_raw")

# robust split on commas / semicolons / new lines
extra_keywords = [k.strip() for k in re.split(r"[,\n;]+", extra_kw_raw) if k.strip()]

st.markdown("---")
submitted = st.button("Start Generating")

# ---------- Generate ----------
if submitted:
    if not address or not city or not state or not zip_code:
        st.error("Please fill in the address, city, state, and ZIP.")
        st.stop()

    auto_keywords = build_keywords_from_selections(
        selected=selections,
        beds=beds,
        baths=baths,
        sqft=int(sqft) if sqft else None,
        lot_size=int(lot_size) if lot_size else None,
        year_built=int(year_built) if year_built else None,
        property_type=property_type,
        extra_keywords=[],
    )
    # Add user-provided extras
    auto_keywords.extend([k.lower() for k in extra_keywords])

    upgrades_bullets = build_upgrades_bullets(selections, custom_lines=[])

    li = ListingInput(
        address=address, city=city, state=state, zip_code=zip_code,
        beds=beds, baths=baths, sqft=int(sqft) if sqft else None, lot_size=int(lot_size) if lot_size else None,
        year_built=int(year_built) if year_built else None, property_type=property_type,
        price=int(price) if price else None, keywords=auto_keywords,
        upgrades_bullets=upgrades_bullets, neighborhood_notes=neighborhood_notes,
        target_buyer_profile=target_buyer_profile, tone=tone,
        mls_char_limit=int(mls_char_limit), detail_level=detail_level,
        highlight_features=[]  # wire back if you want a highlight picker
    )

    with st.spinner("Generating polished copy..."):
        try:
            data, _ = chat_json(
                "You are a meticulous, compliant real estate listing copywriter.",
                build_primary_prompt(li),
                temperature=0.5 if li.detail_level == "Standard" else (0.65 if li.detail_level == "Descriptive" else 0.35),
            )
            data = validate_and_repair(li, data)
            data = ensure_length(li, data)
        except Exception as e:
            st.exception(e)
            st.stop()

    # ------------- Outputs -------------
    st.subheader("MLS Description")
    mls_text = (data.get("mls_description") or "").strip()
    st.write(mls_text)
    st.caption(f"Character count: {len(mls_text)} / {li.mls_char_limit}")

    st.subheader("Social Caption")
    social_caption = (data.get("social_caption") or "").strip()
    st.write(social_caption if social_caption else "— (not generated)")

    st.subheader("Instagram Hashtags")
    hashtags = (data.get("instagram_hashtags") or "").strip()
    st.write(hashtags if hashtags else "— (not generated)")

    st.subheader("60-Second Video Script")
    video_script = (data.get("video_script_60s") or "").strip()
    st.write(video_script if video_script else "— (not generated)")

    st.success("Done! Review for accuracy/compliance before posting.")

    st.markdown("---")
    st.subheader("Auto-Generated Inputs (for reference)")
    st.caption("These are the inputs we fed into the model—edit your selections and regenerate if needed.")
    st.markdown("**Upgrades/Features (bulleted)**")
    st.code(upgrades_bullets or "(none)", language="markdown")
    st.markdown("**SEO Keywords (auto-built)**")
    st.code(", ".join(auto_keywords) or "(none)", language="text")
