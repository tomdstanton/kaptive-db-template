import streamlit as st
import toml
import urllib.request
import urllib.parse
import json
import semver
import io
from re import compile as re_compile
from gb_io import iter as GenbankIterator

st.set_page_config(page_title="Kaptive Database Validator", layout="centered")
st.title("🧬🦠💉 Kaptive Database Validator")
st.markdown("Fill out the fields below to validate your Kaptive database and generate the metadata file.")

# Initialize persistent storage for DOIs
if 'doi_list' not in st.session_state:
    st.session_state.doi_list = []

def parse_database(fh):
    _LOCUS_REGEX = re_compile(r'locus:\s?(.*)$')
    _SEROTYPE_REGEX = re_compile(r'type:\s?(.*)$')
    _EXTRA_REGEX = re_compile(r'Extra genes:\s?(.*)$')
    
    loci, extra = [], []
    for rec in GenbankIterator(fh):
        locus_name, serotype = None, None

        if not (notes := [i.value for i in rec.features[0].qualifiers if i.key == 'note']):
            raise ValueError(f'Locus has no "note" qualifiers: {rec.name}')

        locus_name, serotype = None, None
        for note in notes:  # type: str
            if match := _EXTRA_REGEX.search(note):
                locus_name = match.group(1)
                extra.append(locus_name)
                break

            if not locus_name and (match := _LOCUS_REGEX.search(note)):
                locus_name = match.group(1)

            if not serotype and (match := _SEROTYPE_REGEX.search(note)):
                serotype = match.group(1)

        if not locus_name:
            raise ValueError(f'Locus has no valid "locus" qualifiers: {rec.name}')

        loci.append(f'{locus_name} -> {serotype or "Unknown"}')

    return loci, extra


# Helper Function: Fetch DOIs from Crossref based on title search
@st.cache_data(ttl=3600)
def fetch_crossref_dois(search_term):
    if not search_term.strip():
        return []
    try:
        encoded_term = urllib.parse.quote(search_term)
        url = f"https://api.crossref.org/works?query.title={encoded_term}&select=title,DOI&rows=5"
        
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Kaptive-Metadata-Generator/1.0 (mailto:kaptive.typing@gmail.com)'
        })
        
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            
        items = data.get("message", {}).get("items", [])
        results = []
        for item in items:
            title = item.get("title", ["Unknown Title"])[0]
            doi = item.get("DOI", "No DOI")
            if doi != "No DOI":
                results.append({"title": title, "doi": doi})
        return results
    except Exception:
        return []

# Helper Function: Fetch TaxIDs from NCBI Datasets API
@st.cache_data(ttl=3600) 
def fetch_ncbi_taxids(search_term):
    if not search_term.strip():
        return []

    try:
        encoded_term = urllib.parse.quote(search_term)
        url = f"https://api.ncbi.nlm.nih.gov/datasets/v2alpha/taxonomy/taxon_suggest/{encoded_term}"

        req = urllib.request.Request(url, headers={'User-Agent': 'Kaptive-Metadata-Generator/1.0'})

        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))

        results = []

        if "sci_name_and_ids" in data:
            for item in data["sci_name_and_ids"]:
                tax_id = item.get("tax_id")
                sci_name = item.get("sci_name")
                rank = item.get("rank", "Unknown").title()  

                label = f"{sci_name} ({rank}) [TaxID: {tax_id}]"
                results.append({
                    "label": label,
                    "id": int(tax_id),
                    "name": sci_name
                })
        return results

    except Exception as e:
        return []

# NEW Helper Function: Fetch Repositories for a User/Org
@st.cache_data(ttl=300)
def fetch_github_repos(owner):
    if not owner.strip():
        return []
    
    try:
        # Using sort=updated to show recently active repos first
        url = f"https://api.github.com/users/{urllib.parse.quote(owner)}/repos?per_page=100&sort=updated"
        req = urllib.request.Request(url, headers={'User-Agent': 'Kaptive-Metadata-Generator/1.0'})

        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))

        # Extract just the repository names
        return [repo['name'] for repo in data]
    except Exception:
        # Fails gracefully (e.g., user not found or rate limited)
        return []

@st.cache_data(ttl=300)
def fetch_github_branches(owner, repo):
    if not owner.strip() or not repo.strip():
        return []
        
    try:
        url = f"https://api.github.com/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/branches?per_page=100"
        req = urllib.request.Request(url, headers={'User-Agent': 'Kaptive-Metadata-Generator/1.0'})
        
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            
        return [branch['name'] for branch in data]
    except Exception:
        return []

# Helper Function: Fetch .gbk files from the root of the GitHub repo
@st.cache_data(ttl=300)
def fetch_github_gbk_files(owner, repo, branch):
    if not owner or not repo or not branch:
        return None

    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Kaptive-Metadata-Generator/1.0'})

        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))

        gbk_files = [item['path'] for item in data.get('tree', []) if item['path'].endswith('.gbk')]
        return gbk_files

    except urllib.error.HTTPError:
        return None
    except Exception:
        return None

# Helper Function: Fetch raw database and parse it
@st.cache_data(show_spinner=False, ttl=300)
def fetch_and_validate_genbank(owner, repo, branch, filename):
    if not filename:
        return None, None, "No file provided."
    try:
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{urllib.parse.quote(filename)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Kaptive-Metadata-Generator/1.0'})
        
        with urllib.request.urlopen(req, timeout=10) as response:
            raw_data = response.read()
            
        fh = io.BytesIO(raw_data)
        loci, extra = parse_database(fh)
        return loci, extra, None
    except Exception as e:
        return None, None, str(e)


col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("Database 📂")
    owner = st.text_input("Owner", value="klebgenomics")

    # Fetching repositories dynamically based on the owner input
    repos = fetch_github_repos(owner)
    
    if repos:
        # Keep original workflow seamless by selecting standard repo by default if it exists
        default_index = repos.index("KoSC-surface-antigen-loci") if "KoSC-surface-antigen-loci" in repos else 0
        repo = st.selectbox("Repo", options=repos, index=default_index)
    else:
        st.warning("⚠️ Could not fetch repositories. Please enter manually.")
        repo = st.text_input("Repo", value="KoSC-surface-antigen-loci")

    branches = fetch_github_branches(owner, repo)
    
    if branches:
        # Default to 'main', fallback to 'master', otherwise just the first branch
        default_branch_index = 0
        if "main" in branches:
            default_branch_index = branches.index("main")
        elif "master" in branches:
            default_branch_index = branches.index("master")
            
        branch = st.selectbox("Branch", options=branches, index=default_branch_index)
    else:
        st.warning("⚠️ Could not fetch branches. Please enter manually.")
        branch = st.text_input("Branch", value="main")

    gbk_files = fetch_github_gbk_files(owner, repo, branch)

    if gbk_files is None:
        st.error("⚠️ Repository or branch not found.")
        genbank = st.text_input("GenBank File (Manual Entry)")
    elif len(gbk_files) == 0:
        st.warning(f"No '.gbk' files found in {owner}/{repo} on branch '{branch}'.")
        genbank = st.text_input("GenBank File (Manual Entry)")
    else:
        st.success(f"Found {len(gbk_files)} GenBank file(s)!")
        genbank = st.selectbox("Select GenBank File", options=gbk_files)

    organism_input = st.text_input("Search Organism Name", value="Klebsiella oxytoca")
    ncbi_options = fetch_ncbi_taxids(organism_input)
    
    if ncbi_options:
        selected_option = st.selectbox(
            "Select Verified NCBI Taxonomy Match",
            options=ncbi_options,
            format_func=lambda x: x["label"]
        )
        taxon = selected_option["id"]
        organism = selected_option["name"] 
        st.success(f"Selected Taxon ID: {taxon}")
    else:
        st.warning("No official NCBI records found. Please enter manually:")
        organism = st.text_input("Organism Custom Name", value=organism_input)
        taxon = st.number_input("Taxon ID (Manual)", value=571, step=1)


with col2:
    st.subheader("Biology 🦠")
    prefix = st.text_input("Prefix", value="K")

    org_parts = organism.strip().split()
    genus_part = org_parts[0] if len(org_parts) > 0 else ""
    species_part = org_parts[1] if len(org_parts) > 1 else ""

    genus_letter = genus_part[0].lower() if genus_part else ""
    species_letters = species_part[:3].lower() if species_part else ""
    clean_prefix = prefix.lower().strip()

    suggested_keyword = f"{genus_letter}{species_letters}_{clean_prefix}"
    suggested_name = f"{organism.replace(' ', '_')}_{prefix}"

    keyword = st.text_input("Keyword", value=suggested_keyword)
    name = st.text_input("Database Config Name", value=suggested_name)

    id_threshold = st.slider(
        "ID Threshold (%)", 
        min_value=0.0, 
        max_value=100.0, 
        value=82.5, 
        step=0.5, 
        format="%.1f"
    )
    
    antigen = st.selectbox("Antigen", ["Capsular polysaccharide", "O antigen", "Other"])
    if antigen == "Other":
        antigen = st.text_input("Specify Antigen")

    pathway = st.selectbox("Pathway", ["Wzx/Wzy-dependent", "ABC transporter", "Synthase-dependent", "Other"])
    if pathway == "Other":
        pathway = st.text_input("Specify Pathway")


with col3:
    st.subheader("Curation 📚")
    version_input = st.text_input("Version", value="0.0.0")

    is_valid_version = True
    if not semver.VersionInfo.is_valid(version_input):
        st.error("⚠️ Invalid SemVer format. Must be MAJOR.MINOR.PATCH (e.g., '0.0.0').")
        is_valid_version = False

    version = version_input 
    
    contact_name = st.text_input("Contact Name", value="Kelly Wyres")
    contact_email = st.text_input("Contact Email", value="kaptive.typing@gmail.com")
    
    st.markdown("**Paper DOIs**")
    
    search_query = st.text_input("Search Paper by Title (Crossref)")
    if search_query:
        api_results = fetch_crossref_dois(search_query)
        
        if api_results:
            selected_paper = st.selectbox(
                "Select matching paper:", 
                options=api_results, 
                format_func=lambda x: f"{x['title']} (DOI: {x['doi']})"
            )
            
            if st.button("➕ Add to Database DOIs"):
                if selected_paper['doi'] not in st.session_state.doi_list:
                    st.session_state.doi_list.append(selected_paper['doi'])
                    st.rerun() 
                else:
                    st.warning("This DOI is already in your list.")
        else:
            st.warning("No papers found on Crossref.")

    with st.expander("Manually add a DOI (if not on Crossref)"):
        manual_doi = st.text_input("Enter exact DOI:")
        if st.button("➕ Add Manual DOI") and manual_doi:
            if manual_doi not in st.session_state.doi_list:
                st.session_state.doi_list.append(manual_doi)
                st.rerun()

    if st.session_state.doi_list:
        for i, current_doi in enumerate(st.session_state.doi_list):
            c1, c2 = st.columns([5, 1])
            c1.code(current_doi)
            if c2.button("❌", key=f"remove_doi_{i}"):
                st.session_state.doi_list.pop(i)
                st.rerun()
    else:
        st.info("No DOIs added. Array will default to ['TBD'].")

st.divider()
st.subheader("Database Validation ✅")

is_db_valid = False

if genbank:
    with st.spinner("Fetching and validating GenBank file from GitHub..."):
        loci, extra, err = fetch_and_validate_genbank(owner, repo, branch, genbank)
        
        if err:
            st.error(f"⚠️ **Validation Failed:** {err}")
        else:
            is_db_valid = True
            st.success(f"Database valid! Successfully parsed **{len(loci)}** loci and **{len(extra)}** extra genes.")
            
            val_col1, val_col2 = st.columns(2)
            with val_col1:
                with st.expander("View Loci Details"):
                    if loci:
                        st.write(loci)
                    else:
                        st.info("No loci found.")
            with val_col2:
                with st.expander("View Extra Genes Details"):
                    if extra:
                        st.write(extra)
                    else:
                        st.info("No extra genes found.")
else:
    st.info("Select or enter a GenBank file above to validate.")


# Build the Data Dictionary
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
    "doi": st.session_state.doi_list if len(st.session_state.doi_list) > 0 else ["TBD"],
    "owner": owner,
    "repo": repo,
    "branch": branch,
    "contact": {contact_name: contact_email}
}

st.divider()

# Generate & Preview TOML
toml_string = toml.dumps(metadata)

st.subheader("Live Metadata Preview ♻️")
st.code(toml_string, language="toml")

download_filename = "metadata.toml" 
if genbank and genbank.endswith('.gbk'):
    download_filename = genbank.replace('.gbk', '.toml')

# Download Button Logic
if is_valid_version and is_db_valid:
    st.download_button(
        label=f"⬇️ Download {download_filename}",
        data=toml_string,
        file_name=download_filename,
        mime="application/toml"
    )
elif not is_valid_version:
    st.button(
        label=f"⬇️ Download {download_filename}",
        disabled=True,
        help="Please fix the version formatting error above to enable downloads."
    )
else:
    st.button(
        label=f"⬇️ Download {download_filename}",
        disabled=True,
        help="Download disabled. Please ensure the selected GenBank database is valid."
    )
