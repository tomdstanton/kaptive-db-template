
import streamlit as st
import toml
import urllib.request
import urllib.parse
import json
import semver

st.set_page_config(page_title="Kaptive Metadata Generator", layout="centered")
st.title("🧬 Kaptive Metadata Generator")
st.markdown("Fill out the fields below to generate your Kaptive database `metadata.toml` file.")


# Helper Function: Fetch TaxIDs from NCBI Datasets API
@st.cache_data(ttl=3600)  # Cache results for 1 hour to prevent redundant API calls
def fetch_ncbi_taxids(search_term):
    if not search_term.strip():
        return []

    try:
        # Encode the search string for the URL
        encoded_term = urllib.parse.quote(search_term)
        url = f"https://api.ncbi.nlm.nih.gov/datasets/v2alpha/taxonomy/taxon_suggest/{encoded_term}"

        # Adding a User-Agent is good practice when hitting NCBI servers
        req = urllib.request.Request(url, headers={'User-Agent': 'Kaptive-Metadata-Generator/1.0'})

        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))

        results = []

        # If NCBI finds no matches, it returns an empty object {} instead of an array.
        # We check for the key before trying to loop through it.
        if "sci_name_and_ids" in data:
            for item in data["sci_name_and_ids"]:
                tax_id = item.get("tax_id")
                sci_name = item.get("sci_name")
                rank = item.get("rank", "Unknown").title()  # e.g., SPECIES -> Species

                label = f"{sci_name} ({rank}) [TaxID: {tax_id}]"
                results.append({
                    "label": label,
                    "id": int(tax_id),
                    "name": sci_name
                })
        return results

    except Exception as e:
        # Fails securely, allowing the user to manually enter info below
        return []


# Helper Function: Fetch .gbk files from the root of the GitHub repo
@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_github_gbk_files(owner, repo, branch):
    if not owner or not repo or not branch:
        return None

    try:
        # No recursive flag here; looks strictly at the root directory
        url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Kaptive-Metadata-Generator/1.0'})

        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))

        # Filter root items for files ending in .gbk
        gbk_files = [item['path'] for item in data.get('tree', []) if item['path'].endswith('.gbk')]
        return gbk_files

    except urllib.error.HTTPError:
        return None
    except Exception:
        return None


col1, col2 = st.columns(2)

with col1:
    st.subheader("Biology & Taxonomy")

    # 1. User types the name
    organism_input = st.text_input("Search Organism Name", value="Klebsiella oxytoca")

    # 2. Trigger the Datasets API lookup behind the scenes
    ncbi_options = fetch_ncbi_taxids(organism_input)

    # 3. Present choices dynamically
    if ncbi_options:
        selected_option = st.selectbox(
            "Select Verified NCBI Taxonomy Match",
            options=ncbi_options,
            format_func=lambda x: x["label"]
        )
        taxon = selected_option["id"]
        organism = selected_option["name"]  # Use official scientific name from API
        st.success(f"Selected Taxon ID: {taxon}")
    else:
        st.warning("No official NCBI records found. Please enter manually:")
        organism = st.text_input("Organism Custom Name", value=organism_input)
        taxon = st.number_input("Taxon ID (Manual)", value=571, step=1)

    st.subheader("Basic Info")

    # Collect prefix first so it can feed into both downstream suggestions
    prefix = st.text_input("Prefix", value="K")

    # Safe string parsing for the new keyword rule
    # e.g., "Klebsiella oxytoca Species Complex" -> ["Klebsiella", "oxytoca", "Species", "Complex"]
    org_parts = organism.strip().split()
    genus_part = org_parts[0] if len(org_parts) > 0 else ""
    species_part = org_parts[1] if len(org_parts) > 1 else ""

    # Extract letters safely (handles empty string states gracefully)
    genus_letter = genus_part[0].lower() if genus_part else ""
    species_letters = species_part[:3].lower() if species_part else ""
    clean_prefix = prefix.lower().strip()

    # Calculate both dynamic suggestions
    suggested_keyword = f"{genus_letter}{species_letters}_{clean_prefix}"
    suggested_name = f"{organism.replace(' ', '_')}_{prefix}"

    # Present text inputs populated with your dynamic defaults
    keyword = st.text_input("Keyword", value=suggested_keyword)
    name = st.text_input("Database Config Name", value=suggested_name)
    # Collect the raw input
    version_input = st.text_input("Version", value="0.0.0")

    # Validate the input
    is_valid_version = True
    if not semver.VersionInfo.is_valid(version_input):
        st.error("⚠️ Invalid SemVer format. Must be MAJOR.MINOR.PATCH (e.g., '0.0.0').")
        is_valid_version = False

    version = version_input  # Still map it to the dictionary so the preview works

with col2:
    st.subheader("Repository & Files")
    owner = st.text_input("Owner", value="klebgenomics")
    repo = st.text_input("Repo", value="KoSC-surface-antigen-loci")
    branch = st.text_input("Branch", value="main")

    # Trigger the GitHub API lookup
    gbk_files = fetch_github_gbk_files(owner, repo, branch)

    # Dynamic Validation & Dropdown
    if gbk_files is None:
        st.error("⚠️ Repository not found. Please check Owner, Repo, and Branch.")
        genbank = st.text_input("GenBank File (Manual Entry)")
    elif len(gbk_files) == 0:
        st.warning(f"No '.gbk' files found in {owner}/{repo} on branch '{branch}'.")
        genbank = st.text_input("GenBank File (Manual Entry)")
    else:
        st.success(f"Found {len(gbk_files)} GenBank file(s)!")
        genbank = st.selectbox("Select GenBank File", options=gbk_files)

    st.subheader("Database Config")
    id_threshold = st.number_input("ID Threshold (%)", value=82.5, format="%.1f")

    st.subheader("Biological Attributes")
    antigen = st.selectbox("Antigen", ["Capsular polysaccharide", "O antigen", "Other"])
    if antigen == "Other":
        antigen = st.text_input("Specify Antigen")

    pathway = st.selectbox("Pathway", ["Wzx/Wzy-dependent", "ABC transporter", "Synthase-dependent", "Other"])
    if pathway == "Other":
        pathway = st.text_input("Specify Pathway")

    st.subheader("Contact & Citations")
    doi = st.text_input("DOI", value="TBD")
    contact_name = st.text_input("Contact Name", value="Kelly Wyres")
    contact_email = st.text_input("Contact Email", value="kaptive.typing@gmail.com")

# 3. Build the Data Dictionary
metadata = {
    "name": name,
    "keyword": keyword,
    "genbank": genbank,
    "organism": organism,
    "taxon": int(taxon),
    "antigen": antigen,
    "pathway": pathway,
    "prefix": prefix,
    "version": version,
    "id_threshold": float(id_threshold),
    "doi": [doi],
    "owner": owner,
    "repo": repo,
    "branch": branch,
    "contact": {contact_name: contact_email}
}

st.divider()

# 4. Generate & Preview TOML
toml_string = toml.dumps(metadata)

st.subheader("Live Preview")
st.code(toml_string, language="toml")

# Determine the dynamic download filename
download_filename = "metadata.toml"  # Default fallback
if genbank and genbank.endswith('.gbk'):
    download_filename = genbank.replace('.gbk', '.toml')

# 5. Download Button
if is_valid_version:
    st.download_button(
        label=f"⬇️ Download {download_filename}",
        data=toml_string,
        file_name=download_filename,
        mime="application/toml"
    )
else:
    st.button(
        label=f"⬇️ Download {download_filename}",
        disabled=True,
        help="Please fix the version formatting error above to enable downloads."
    )
