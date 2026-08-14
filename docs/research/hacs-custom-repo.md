# HACS custom-repository acceptance requirements (integration type)

Researched 2026-08-14 against the official docs (hacs.xyz) and the HACS integration source
(`github.com/hacs/integration`, `main` branch). Source-code claims cite file paths under
`custom_components/hacs/` in that repo, with function names as line context.

## TL;DR

HACS will accept `xpenno255/ot_thermostat_control` as a **custom** repository in either layout:
`content_in_root: true` in a root `hacs.json` is genuinely supported for integrations by both docs and
source (`repositories/integration.py::validate_repository` sets `content.path.remote = ""` when the flag
is set), but it makes HACS extract the **entire repo tree** (docs, .github, CLAUDE.md, everything) into
`config/custom_components/<domain>/`, so restructuring to `custom_components/ot_thermostat_control/` is
strongly preferred and is required anyway for default-store inclusion and hassfest. At custom-repo add
time HACS only checks: repo is public/reachable on GitHub, not archived, not on HACS's removed list, has
a compliant content path, and has a `manifest.json` with a `domain` key — `hacs.json`, description,
topics, and releases are **not** enforced at add time (those rules are action/CI-only). Versions come
from GitHub **releases** (not bare tags); with no releases HACS installs the default branch and shows the
7-char commit SHA as the version. HACS never adopts a manually-copied folder; downloading through HACS
writes over the same `custom_components/<domain>` path (config entries survive; a restart-required issue
is raised), and downgrade = "Redownload" with a specific release version picked in the UI.

## 1. Required repo structure: `content_in_root` vs `custom_components/<domain>/`

**Docs.** The integration publish doc requires
`ROOT_OF_THE_REPO/custom_components/INTEGRATION_NAME/` with exactly one subdirectory under
`custom_components/`, *but* explicitly allows the root layout: "if you have `content_in_root` set to
`true` in `hacs.json` this is valid" (https://hacs.xyz/docs/publish/integration).

**Source.** `repositories/integration.py::validate_repository` confirms this is a first-class path:

```python
if self.repository_manifest.content_in_root:
    self.content.path.remote = ""

if self.content.path.remote == "custom_components":
    name = get_first_directory_in_directory(self.tree, "custom_components")
    if name is None:
        ...
        raise HacsException(
            f"{self.string} Repository structure for {self.ref.replace('tags/', '')} is not compliant"
        )
    self.content.path.remote = f"custom_components/{name}"
```

(https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/repositories/integration.py)

So with `content_in_root: true` the structure check is bypassed entirely and `manifest.json` is read from
the repo root (`integration.py::async_get_integration_manifest` builds the path as
`f"{self.content.path.remote}/manifest.json"`, i.e. `manifest.json` at root). Without the flag and
without a `custom_components/<dir>/`, registration fails with "Repository structure ... is not
compliant" — that is the exact error the repo would hit today if added with no `hacs.json`.

**Why restructuring is still preferred.** The download path
(`repositories/base.py::download_repository_zip`) extracts every zipball entry whose path starts with
`content.path.remote` into `content.path.local` (= `config/custom_components/<domain>`):

```python
if (
    filename.startswith(self.content.path.remote)
    and filename != self.content.path.remote
):
```

With `content_in_root: true`, `content.path.remote` is `""`, so **every file in the repository** —
README, docs/, .github/, CLAUDE.md, tests — is extracted into the live
`config/custom_components/<domain>/` directory
(https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/repositories/base.py,
`download_repository_zip`). Additionally, the standard layout is a hard requirement for HACS
default-store inclusion and for the hassfest action (https://hacs.xyz/docs/publish/include). Verdict:
`content_in_root: true` is *sufficient* for custom-repo acceptance, but restructuring to
`custom_components/ot_thermostat_control/` is the correct move.

## 2. `hacs.json` and `manifest.json` requirements — HACS vs Home Assistant

### hacs.json

Docs say the file "must be located in the root of your repository" and list its fields
(https://hacs.xyz/docs/publish/start). The runtime schema (`utils/validate.py`,
`HACS_MANIFEST_JSON_SCHEMA`) is:

- `vol.Required("name"): str` — the only required key
- Optional: `content_in_root` (bool), `country`, `filename` (str), `hacs` (min HACS version, str),
  `hide_default_branch` (bool), `homeassistant` (min HA version, str), `persistent_directory` (str),
  `render_readme` (bool), `zip_release` (bool); extra keys are rejected (`vol.PREVENT_EXTRA`)
  (https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/utils/validate.py).

**However, at custom-repo add time hacs.json is optional.** `repositories/base.py::common_validate`
only reads it *if present*:

```python
if RepositoryFile.HACS_JSON in [x.filename for x in self.tree]:
    if manifest := await self.async_get_hacs_json():
        self.repository_manifest = HacsManifest.from_dict(manifest)
```

The rule that *requires* hacs.json (`validate/hacsjson.py`, which also enforces `filename` when
`zip_release` is set) subclasses `ActionValidationBase`, and `validate/manager.py::
async_run_repository_checks` starts with `if not self.hacs.system.action: return` — i.e. those checks
only run in the HACS Action CI used for default-store submission, never inside a user's Home Assistant
(https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/manager.py).
Caveat: if the content stays at the repo root, `hacs.json` with `content_in_root: true` becomes
effectively mandatory, because it is the only way the structure check passes (see §1).

- `zip_release: true` + `filename` tells HACS to download a named zip asset from the GitHub release
  instead of the repo archive (`repositories/base.py::async_install_repository`:
  `if self.repository_manifest.zip_release and self.repository_manifest.filename:
  await self.download_zip_files(...)`). Integrations-only per docs; irrelevant here unless you start
  shipping build artifacts.
- `homeassistant` / `hacs` set minimum versions HACS enforces before download.
- `hide_default_branch: true` "Prevents downloads of the default branch" in the version picker
  (https://hacs.xyz/docs/publish/start).

### manifest.json

Two different enforcement layers:

- **Enforced by HACS at custom-repo add time** (`repositories/integration.py::validate_repository`):
  the file must exist at the content path — `async_get_integration_manifest` raises
  `HacsException("No manifest.json file found '<path>'")` if absent — and must contain `domain`
  (`self.data.domain = manifest["domain"]`; a missing key appends
  `"Missing expected key '<key>' in manifest.json"` to `validate.errors`, which causes
  `base.py::async_register_repository` to refuse the repo). `codeowners`, `name`, `config_flow` are read
  with `.get()` — optional at add time.
- **Enforced by the HACS Action only** (default-store CI, `validate/integration_manifest.py` against
  `INTEGRATION_MANIFEST_JSON_SCHEMA` in `utils/validate.py`): `vol.Required` for `codeowners` (list),
  `documentation` (url), `domain` (str), `issue_tracker` (url), `name` (str), `version`
  (`vol.Coerce(AwesomeVersion)`); extra keys allowed. The publish docs mirror this list: "domain,
  documentation, issue_tracker, codeowners, name, and version" (https://hacs.xyz/docs/publish/integration).
  The `url_validator` checks URL *shape*, not that the URL resolves or points at the right repo — so a
  wrong-but-well-formed URL passes even CI validation.
- **Enforced by Home Assistant itself**, independent of HACS: since HA 2021.6, custom integrations
  without a `version` key in `manifest.json` fail to load at all — that requirement is HA core's, not
  HACS's (HACS merely coerces it in the CI schema above).

## 3. Releases/tags vs default-branch installs

**How versions are detected.** `repositories/base.py::common_update_data` calls
`get_releases(prerelease=True, returnlimit=30)`, which lists **GitHub releases** via
`githubapi.repos.releases.list` and skips drafts. The newest non-prerelease release's `tag_name` becomes
`data.last_version`; prereleases populate `data.prerelease` and are offered only when `show_beta` is on
(`filtered_releases` filter). The docs state it plainly: "Just publishing tags is not enough, you need to
publish releases" (https://hacs.xyz/docs/publish/start). Bare git tags without a release are invisible to
HACS.

**What gets installed.** `repositories/base.py::version_to_download`: `selected_tag` if the user picked
one, else `data.last_version` (latest release), else `data.default_branch or "main"`. In
`async_install_repository`, a release version becomes `ref = f"tags/{version}"` and the tag's zipball is
downloaded; the default branch downloads the branch head archive (`download_repository_zip` tries the
`tags` archive variant, then falls back to `heads`).

**No releases at all.** The repo still works: HACS installs the default branch, and "the 7 first
characters of the last commit will be used" as the displayed version
(https://hacs.xyz/docs/publish/start; source: `common_update_data` sets `self.data.releases = False` on
`HacsException` from `get_releases` and falls through to the default branch ref). Updates then mean
"newer commit on default branch" rather than semantic versions. Publishing releases is "preferred but not
required" (https://hacs.xyz/docs/publish/integration) — but is a hard requirement for default-store
inclusion ("Create a new GitHub release (not just a tag, a full release)",
https://hacs.xyz/docs/publish/include).

**zip_release effect.** With `zip_release: true` + `filename` in hacs.json, HACS downloads the named
asset from the GitHub release instead of the source archive
(`async_install_repository` → `download_zip_files` → `github_release_asset(...)` →
`async_download_zip_file`, which extracts the asset zip into `content.path.local`). This makes releases
effectively mandatory, since the asset only exists on a release.

## 4. Interaction with a pre-existing manually-copied `custom_components/<domain>/`

**HACS never adopts manual installs.** "HACS will not scan the local file system for existing elements
... If HACS did not initially download the element, there's no way to know which version you have";
existing elements "will need to be downloaded again via HACS"
(https://hacs.xyz/docs/faq/existing_elements). There is no adoption code path in the source: `installed`
status comes only from HACS's own store (`data.installed` set in `async_install_repository` after a
successful download).

**Install over the manual copy — what actually happens.** The local target is always
`config/custom_components/<domain>` (`integration.py::localpath`), the same directory as the manual copy.
In `repositories/base.py::async_install_repository`:

- A safety `Backup` of the local dir is taken **only if `self.data.installed`** is true, i.e. only for
  repos HACS itself previously downloaded (`if self.data.installed and not self.content.single: backup =
  Backup(...)`). `Backup.create()` copies the dir to a temp `hacs_backup` location **and deletes the
  original** (`utils/backup.py`), then a fresh download lands; on download errors `backup.restore()`
  rolls the old files back. So for HACS-managed repos the flow matches the FAQ: "The local target
  directory is deleted. A new local target directory is created. All expected files are downloaded"
  (https://hacs.xyz/docs/faq/download).
- For a **not-yet-HACS-installed** repo sitting on top of a manual copy, `data.installed` is false, so no
  backup and **no pre-delete** happens: `download_repository_zip` runs `zip_file.extractall(
  self.content.path.local, extractable)` straight over the existing directory. Files with the same names
  are overwritten; stale files that only exist in the manual copy are left behind. Here the docs (FAQ
  says the dir is deleted first) and the source disagree for this first-install-over-manual-copy case —
  trust the source: it overwrites in place without clearing. Practical consequence: delete the manual
  folder yourself (or make sure it is identical) before the first HACS download.

**Config entries survive.** Nothing in the install path touches HA's `.storage` config entries — HACS
only replaces files under `custom_components/<domain>`. Since the `domain` is unchanged, existing config
entries reattach to the newly downloaded code after restart. Post-install,
`integration.py::async_post_installation` sets `pending_restart = True` and raises a
`restart_required` repair issue (severity WARNING); only a *first* install of a config-flow integration
skips the restart requirement (`if self.data.first_install: self.pending_restart = False`).

**Rollback/downgrade.** Supported and release-based: the dashboard's "Redownload" action lets you pick a
version — "By default, the newest version of a repository is downloaded. If needed, you can select a
specific version" (https://hacs.xyz/docs/use/repositories/dashboard). In the source this is the
`hacs/repository/download` websocket command with an optional `version`, plus `hacs/repository/version`
(select), `hacs/repository/releases` (list), and `hacs/repository/beta`
(https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/websocket/repository.py);
`async_install_repository(version=...)` then installs `tags/<version>`. Only published release tags (and
the default branch, unless `hide_default_branch`) are offered — no releases means no downgrade targets.
"Update information" refreshes metadata without touching files; "Remove" deletes the downloaded
directory (`repositories/base.py::uninstall` → `remove_local_directory`).

## Custom repository vs HACS default store

The ticket is about **custom-repo** acceptance, which is a much smaller bar than default-store inclusion.

**Checks that actually run when adding via the "Custom repositories" dialog** (frontend →
`hacs/repositories/add` websocket in `websocket/repositories.py` → `base.py::async_register_repository`
with `check=True` → `repositories/base.py::async_registration` → `integration.py::validate_repository`):

1. URL parses to a `owner/repo` and the category ("integration") is enabled (`websocket/repositories.py`).
2. Not a hard-blocked repo (`home-assistant/core`, add-on repos) and not on HACS's removed/blacklist
   (`common_update_data`: "Repository has been requested to be removed.").
3. Repo exists and is reachable via the GitHub API — private/missing repos fail with "Repository does not
   exist." (`common_update_data`); docs: "Only public repositories on GitHub will work with HACS"
   (https://hacs.xyz/docs/publish/start).
4. Not archived ("Repository is archived.", `HacsRepositoryArchivedException`).
5. Git tree is fetchable and structure is compliant: a single `custom_components/<dir>/`, or
   `content_in_root: true` in hacs.json (§1).
6. `manifest.json` exists at the content path and has a `domain` key (§2). Any `validate.errors` →
   `async_register_repository` adds the repo to `common.skip` and returns the errors — the add fails.

**Not checked at add time** (despite appearing in https://hacs.xyz/docs/publish/start): description,
topics, README, brands, license, issues-enabled, releases, and even hacs.json itself. All of those live
in `custom_components/hacs/validate/` (archived, brands, description, hacsjson, images, information,
integration_manifest, issues, license, topics) and are gated behind `if not self.hacs.system.action:
return` in `validate/manager.py` — they run only in the **HACS Action** CI used when submitting to the
default store (https://hacs.xyz/docs/publish/include: HACS Action + hassfest must pass, brands entry with
icon, "hacs.json file contains at least a `name`", at least one release, description/issues/topics
required, then a PR to `hacs/default`). Where the publish docs say these are needed and the runtime
source doesn't enforce them, the source wins for custom-repo acceptance — but they're still good hygiene
and become mandatory the day the repo is submitted to the default store.

## Recommendations for this repo (`xpenno255/ot_thermostat_control`)

1. **Restructure rather than `content_in_root`.** Move the component files into
   `custom_components/ot_thermostat_control/` (manifest.json, `__init__.py`, coordinator.py, etc.), keep
   README/docs/CLAUDE.md at the repo root. This avoids HACS dumping the whole repo (docs, .github,
   agent files) into the live HA config dir on every download (§1), matches HA conventions, and keeps the
   default-store/hassfest door open. `content_in_root: true` works but is the worse option.
2. **Add a minimal root `hacs.json`:**
   ```json
   {
     "name": "OpenTherm Thermostat Control",
     "homeassistant": "<minimum HA version you actually support>"
   }
   ```
   `name` is the only required key; add `homeassistant` only if you know the floor. No
   `content_in_root`, `zip_release`, or `filename` needed. (Strictly optional for custom-repo add once
   restructured, but required for default store and it controls the display name.)
3. **Fix manifest.json URLs.** The current `documentation` and `issue_tracker` point at
   `https://github.com/xpenno255/ha-ot-thermostat-control` — the wrong repo name; the real repo is
   `xpenno255/ot_thermostat_control`. HACS's runtime add-time check only requires the `domain` key, and
   even the CI-only schema's `url_validator` checks URL shape, not that it resolves — so the wrong URLs
   will not block acceptance, but they send users and bug reports to a dead repo. Correct both to
   `https://github.com/xpenno255/ot_thermostat_control` (issue_tracker → `.../issues`).
4. **Manifest keys.** `version: 1.11.0`, `issue_tracker`, and `documentation` are already present; keep
   `version` maintained (HA core requires it to load the integration at all). Ensure `domain`, `name`,
   and `codeowners` (e.g. `["@xpenno255"]`) are present so the CI schema is satisfied too.
5. **Repo metadata.** Make sure the GitHub repo is public, has a one-line description, topics, and a
   README — not enforced at custom-repo add time, but the docs list them and the default store requires
   them.
6. **Publish GitHub releases, not bare tags.** Tag `v1.11.0` (or `1.11.0`) *and* create a release from
   it for every version; keep the release tag in sync with `manifest.json`'s `version`. That gives HACS
   real update detection and enables downgrades via "Redownload → select version". Without releases,
   users get default-branch commit installs with 7-char SHA versions and no version picker.
7. **First download over the existing manual copy.** Anyone who already has the folder manually copied
   into `config/custom_components/ot_thermostat_control/` should delete it (or accept overwrite-in-place
   with possible stale leftovers) before the first HACS download; config entries survive, and HACS will
   raise a restart-required repair issue after download (§4).

## Sources

Docs (hacs.xyz):
- https://hacs.xyz/docs/publish/start — general publish requirements, hacs.json fields, versioning ("publish releases, not just tags"; commit-SHA fallback)
- https://hacs.xyz/docs/publish/integration — integration structure, `content_in_root` validity, required manifest.json keys, releases "preferred but not required"
- https://hacs.xyz/docs/publish/include — default-store inclusion requirements (HACS Action, hassfest, brands, release required)
- https://hacs.xyz/docs/faq/custom_repositories — custom-repo add flow, "known structure" requirement
- https://hacs.xyz/docs/faq/existing_elements — HACS does not scan/adopt manual installs
- https://hacs.xyz/docs/faq/download — documented download sequence (delete → recreate → download)
- https://hacs.xyz/docs/faq — FAQ index
- https://hacs.xyz/docs/use/repositories/dashboard — Redownload / select specific version / Update information / Remove

Source (github.com/hacs/integration, branch `main`, under `custom_components/hacs/`):
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/repositories/integration.py — `validate_repository` (content_in_root, structure error, manifest `domain`), `localpath`, `async_get_integration_manifest`, `async_post_installation` (restart issue)
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/repositories/base.py — `common_validate`, `common_update_data` (archived/removed/releases), `get_releases`, `version_to_download`, `async_registration`, `async_install_repository` (backup gating on `data.installed`, zip_release branch), `download_repository_zip` (extract-over, remote-path filter), `download_content`, `download_zip_files`, `remove_local_directory`, `uninstall`
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/base.py — `async_register_repository` signature (`check=True`), skip-on-errors behavior, blocked repos
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/utils/backup.py — `Backup.create/restore/cleanup` (copy-then-delete semantics)
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/utils/validate.py — `HACS_MANIFEST_JSON_SCHEMA` (only `name` required), `INTEGRATION_MANIFEST_JSON_SCHEMA` (six required keys, `url_validator`)
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/manager.py — `async_run_repository_checks` gated on `hacs.system.action` (CI-only rules)
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/hacsjson.py — action-only hacs.json rule (`zip_release` ⇒ `filename`)
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/validate/integration_manifest.py — action-only manifest schema rule
- https://api.github.com/repos/hacs/integration/contents/custom_components/hacs/validate — rule inventory
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/websocket/repositories.py — `hacs/repositories/add` handler
- https://raw.githubusercontent.com/hacs/integration/main/custom_components/hacs/websocket/repository.py — `hacs/repository/download` (optional `version`), `version`, `releases`, `beta` handlers
