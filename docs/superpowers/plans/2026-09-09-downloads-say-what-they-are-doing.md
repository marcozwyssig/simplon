# Downloads say what they are doing, and uploads stop being swallowed - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a long transfer says it is alive. Downwards that is one kernel function with a progress bar and
three call sites on it; upwards it is the one step whose tool already prints progress and whose progress
the kernel throws away.

**Tickets:** si#142 (downloads are silent: one kernel fetch with a bar), si#143 (uploads: simplon uploads
no bytes itself, so the fix is that the tool's own progress reaches the user).

**Why one lane and one PR.** The two halves share a subject and nothing else - no module, no function, no
test file. They are together because they are the same complaint measured in two directions, and because
si#143's whole content is a rule about when output may be captured, which only reads as a rule beside the
half that does its own reporting.

**Architecture:** a new top-level module `src/simplon/fetch.py`, two small additions to `simplon.log`
(the voice already exists and must not be reinvented), three call sites edited, one classification added
to `simplon.surface`, one page paragraph, and - for si#143 - one `run.run` turned into `run.stream` in
`src/simplon/tasks/asset.py` plus the capture rule stated once in `src/simplon/run.py`.

**Tech Stack:** Python 3.11+, pytest, mypy. **No new dependency.** `pyproject.toml` lines 45-48 record
why the kernel declares no rich and imports nothing from it, and the same argument holds against `tqdm`:
a kernel every product installs does not acquire a dependency in order to draw a bar. `urllib.request`,
`shutil.get_terminal_size`, `time.monotonic` and about thirty lines are the whole implementation.

## Global Constraints

- **No new catalogue coordinate.** Nothing here is a command. `fetch.download` is reached by import and
  `asset.publish` already has its coordinate.
- **No new dependency, declared or undeclared.** Importing an undeclared `rich` is worse than declaring
  it, not better: `pyproject.toml` says a dependency we do not import is a claim we cannot keep, and its
  mirror is that an import we do not declare is a claim we cannot make.
- **A progress bar is display, so a test over its format string proves nothing.** Every behavioural
  claim below is driven against a real HTTP server on a real socket, over a real pty for the TTY half.
  The only unit tests over pure functions are about ARITHMETIC (a percentage that cannot exceed 100, an
  unknown total that produces no percentage), never about the shape of a line.
- **See it red.** Every assertion is watched failing for the right reason before the code that satisfies
  it exists.
- **Do not build the symmetric upload thing.** si#143 says it in as many words: no Python uploader, no
  shared upload helper with no caller. The upload half is a `capture=` decision and a docstring.
- **Surgical.** The call sites carry logic about caching, extraction and failure messages. None of it
  moves.

**Before Task 1, read** `src/simplon/log.py` and `src/simplon/steplog.py` in full. The kernel has an
established voice for a step in progress - `\033[1;34m[HH:MM:SS] ==>\033[0m ` for what is happening and
`\033[1;32m[HH:MM:SS]  OK\033[0m ` for what happened - and a bar that invents its own prefix will look
bolted on and will be a second source for a string the moment somebody changes the first one.

**Baseline, measured on `origin/main` (`0f27e6c`) in a throwaway worktree before a line was changed:**

- `./simplon.sh test all` -> `4 failed, 2730 passed, 3 skipped in 39.97s`, process rc 1. The four are
  pre-existing and unrelated: three `test_tasks_docs.py` uid checks (this container runs as root, which
  is the condition they assert against) and `test_releases_page.py`'s ticket-section check, which
  another branch owns.
- `./simplon.sh test typecheck-python` -> `Success: no issues found in 84 source files`, 3.4s.

---

## Task 1: the test harness, before the thing it tests

**Files:** `tests/test_fetch.py` (new)

**Interfaces produced:** a `_serve(handler)` fixture yielding a base URL, and a `_capture(tty=...)`
context manager yielding what the process actually wrote to file descriptor 1.

This is a task of its own because the harness is the whole proof standard, and building it after the
implementation is how a test ends up shaped to the code rather than to the behaviour.

- [ ] **Step 1: the server.** `http.server.ThreadingHTTPServer` on port 0 in a daemon thread, with a
  handler dispatching on path:

  - `/whole` - `Content-Length: N`, then N bytes, written in chunks with a small sleep so a bar has
    something to repaint over.
  - `/nolength` - HTTP/1.0, no `Content-Length` at all, body then close. EOF is the end.
  - `/half` - `Content-Length: N`, then N//2 bytes, then the connection is closed.
  - `/blackhole` - accepts, answers nothing, sleeps (bounded, so a broken test cannot wedge the suite).

  **The scheme guard versus the local server, decided by spike rather than by argument.** `download`
  refuses anything but https, and a local server is `http://127.0.0.1:<port>`. Two ways out:

  1. serve TLS from a self-signed certificate generated with `cryptography` (already a kernel
     dependency, and already imported lazily for WireGuard keys) and point `SSL_CERT_FILE` at it, so
     every driven test runs over real https and the guard is never bypassed;
  2. keep the guard in ONE module constant and let the mechanics tests monkeypatch it to admit `http`.

  (2) was the expected answer, on the argument that a TLS handshake under every test adds a way for the
  suite to go red that has nothing to do with the subject - in particular that an abrupt close mid-TLS
  would surface as an `SSLError` and hide the truncation semantics the `/half` case exists to expose.
  **The spike says otherwise, so take (1).** Measured, against a self-signed `ThreadingHTTPServer` with
  `SSL_CERT_FILE` set:

  ```
  /whole     -> read=5000 cl=5000 enc=None
  /nolength  -> read=5000 cl=None  enc=None
  /half      -> read=2500 cl=5000  enc=None      <- no exception at all
  /blackhole -> TimeoutError: The read operation timed out   in 0.50s
  ```

  All four behave over TLS exactly as they do in the clear, because Python's `SSLSocket` is created
  with `suppress_ragged_eofs=True` and returns `b""` on a close with no `close_notify`. So the cost of
  (1) is a certificate fixture and nothing else, and the benefit is that no test in this file turns the
  guard off. Generate the key with EC rather than RSA - a session-scoped RSA-2048 keygen is a tenth of
  a second the suite has no reason to spend.

  The guard still gets its OWN tests against `http://`, `file://` and `ftp://`, which is where its
  evidence belongs.

- [ ] **Step 2: the capture.** Progress goes to a child of `sys.stdout`, so a test that swaps
  `sys.stdout` for a `StringIO` with a lying `isatty` proves the BRANCH and not the detection. Use real
  file descriptors instead:

  ```python
  @contextmanager
  def _capture(*, tty: bool):
      """What fd 1 really received, with fd 1 really being (or not being) a terminal."""
      if tty:
          master, slave = pty.openpty()
          write_fd, read_fd = slave, master
      else:
          read_fd, write_fd = os.pipe()
      saved = os.dup(1)
      ...
  ```

  Drain `read_fd` non-blockingly after the call, restore fd 1, and return the bytes decoded. The
  outputs under test are a few hundred bytes, well under a pipe's and a pty's buffer, so no draining
  thread is needed - but assert the drain is complete rather than assuming it.

  `sys.stdout` must be rebound to a stream on the new fd 1 for the duration, because `print` holds its
  own buffered wrapper over the ORIGINAL fd.

- [ ] **Step 3: see the harness itself work.** Before any `fetch` exists, write one throwaway check
  that `_capture(tty=True)` reports `isatty()` true and `_capture(tty=False)` reports it false, and that
  a `print` inside each comes back out. A harness nobody verified is where a green suite comes from.

---

## Task 2: `simplon.fetch.download` (si#142)

**Files:** `src/simplon/fetch.py` (new), `src/simplon/log.py`, `tests/test_fetch.py`

**Interfaces produced:**

```python
DEFAULT_TIMEOUT_S = 30.0
ALLOWED_SCHEMES = frozenset({"https"})

class DownloadError(RuntimeError): ...

def download(url: str, dest: Path, *, label: str = "",
             timeout: float = DEFAULT_TIMEOUT_S) -> Path: ...
```

and in `simplon.log`:

```python
def inplace(msg: str) -> None: ...   # `info`'s line, repainted over itself
def clear_line() -> None: ...        # leave the line empty for whatever prints next
```

**Why two lines go into `log.py` rather than into `fetch.py`.** The prefix is
`\033[1;34m[{ts}] ==>\033[0m {msg}` and it is already written once. A bar that spells it out again is a
second source for a string, which is the shape this repository has been burned by repeatedly - and the
sentence that argues it is already in `CLAUDE.md`. `inplace` is `info` with `\033[K` (erase to end of
line) and `\r` instead of a newline; `clear_line` is what lets the closing `ok` start from an empty
line instead of overprinting a longer bar.

- [ ] **Step 1: write the failing driven tests.** Five behaviours, each named for what it protects:

```python
def test_a_terminal_gets_one_line_repainted_rather_than_a_page_of_them(tmp_path):
    """The TTY half. A bar is only a bar if it paints over itself."""
    with _capture(tty=True) as out:
        fetch.download(f"{base}/whole", tmp_path / "f.bin")
    text = out()
    assert text.count("\r") >= 2, "nothing was repainted, so this is not a bar"
    assert "%" in text
    assert len([ln for ln in text.split("\n") if ln.strip()]) <= 2, \
        "a terminal got more than the bar line and its closing line"


def test_a_pipe_gets_no_carriage_return_at_all(tmp_path):
    """THE MAIN CORRECTNESS QUESTION. This runs in CI far more often than in a terminal, and `\\r`
    into a GitHub Actions log is a smear or a thousand lines."""
    with _capture(tty=False) as out:
        fetch.download(f"{base}/whole", tmp_path / "f.bin")
    text = out()
    assert "\r" not in text
    assert "\033[" not in text.replace("\033[1;32m", "").replace("\033[1;34m", "").replace("\033[0m", ""), \
        "a cursor-movement escape reached a log file"
    assert text.strip(), "a pipe was told nothing at all, which is the defect this ticket is about"


def test_a_response_with_no_content_length_never_claims_a_percentage(tmp_path):
    """A server may send none, or one describing a compressed body."""
    with _capture(tty=True) as out:
        fetch.download(f"{base}/nolength", tmp_path / "f.bin")
    assert "%" not in out()
    assert (tmp_path / "f.bin").read_bytes() == BODY


def test_a_connection_that_dies_halfway_leaves_nothing_under_the_final_name(tmp_path):
    """A half-written docker.tgz that a later run treats as cached hides for weeks."""
    dest = tmp_path / "f.bin"
    with pytest.raises(fetch.DownloadError):
        fetch.download(f"{base}/half", dest)
    assert not dest.exists()
    assert list(tmp_path.iterdir()) == [], "a temporary file was left behind"


def test_a_server_that_accepts_and_never_answers_fails_instead_of_hanging(tmp_path):
    """`urlretrieve` has no timeout, so a hung server hangs the command forever with no output -
    the second half of the same complaint."""
    started = time.monotonic()
    with pytest.raises(fetch.DownloadError):
        fetch.download(f"{base}/blackhole", tmp_path / "f.bin", timeout=0.5)
    assert time.monotonic() - started < 10
```

  Plus the guard's own three, which need no server:

```python
@pytest.mark.parametrize("url", ["http://example.com/x", "file:///etc/passwd", "ftp://h/x"])
def test_only_https_is_fetched(url, tmp_path):
    """The argument both `# noqa: S310` comments made in prose, made once in code instead."""
    with pytest.raises(fetch.DownloadError, match="https"):
        fetch.download(url, tmp_path / "f.bin")
```

- [ ] **Step 2: watch every one of them fail** on `AttributeError: module 'simplon' has no attribute
  'fetch'` or `ModuleNotFoundError`, and no other reason. Import errors are not evidence; re-run after
  the module exists and empty, so each fails on ITS assertion.

- [ ] **Step 3: implement `log.inplace` and `log.clear_line`,** and add nothing else to that module.

- [ ] **Step 4: implement `fetch.download`.** The shape, with the five requirements marked:

  1. **scheme** - `urlsplit(url).scheme` against `ALLOWED_SCHEMES` BEFORE anything opens, and again on
     `response.url` after redirects, because urllib follows them and a redirect to `http://` would
     otherwise walk straight through the guard.
  2. **timeout** - `urlopen(url, timeout=timeout)`. It is a socket timeout, so it bounds the connect
     AND every individual read: a slow 60 MB download is fine, a stall of `timeout` seconds is not.
  3. **temporary name** - `tempfile.mkstemp(dir=dest.parent, prefix=dest.name + ".", suffix=".part")`
     so two concurrent runs cannot collide, `os.replace` onto `dest` at the end (same directory, so the
     rename is atomic), and `finally: unlink` on every path out.
  4. **total** - `Content-Length` when present, `None` otherwise, AND `None` when `Content-Encoding` is
     anything but absent or `identity`, because a length that describes the compressed body is a lie
     the bar would repeat.
  5. **the short-body check, which the harness forced into the design.** Measured, and it is the
     `/half` line of the spike above: `HTTPResponse.read(amt)` on a truncated body returns `b""`
     and raises NOTHING. So a loop that
     trusts EOF renames a half file onto the final name - exactly the defect requirement 3 exists to
     prevent, arriving through the door requirement 3 was not watching. After the loop:
     `if total is not None and received != total: raise DownloadError(...)`.

  Everything urllib can raise (`URLError`, `HTTPError`, `TimeoutError`, `OSError`) is wrapped in
  `DownloadError` with `from exc`, so a consuming product has ONE type to catch and still has the cause.

- [ ] **Step 5: implement the reporting,** and keep it in pure functions so the arithmetic is testable
  apart from the I/O:

  - `human_bytes(n)` - decimal SI (`947 B`, `2.4 MB`, `1.06 GB`). Decimal rather than 1024-based
    because the number beside it is a `Content-Length`, which is what a server advertises and what a
    release page prints; `MB` meaning `MiB` is the ambiguity, and `MiB` everywhere is louder than the
    subject deserves.
  - `render(label, received, total, elapsed, columns, tick)` - one line, truncated to `columns - 1` so
    it can never wrap. Wrapping is not cosmetic here: a wrapped `\r` line leaves a trail of half-lines,
    which is the exact failure the TTY branch exists to avoid.
  - determinate: `label [########------------]  42%  1.0/2.4 MB  3.1 MB/s`, percentage clamped at 100.
  - indeterminate: no bar and no percentage - `label -  1.0 MB  3.1 MB/s`, where `-` cycles through
    `-\|/` so a stalled transfer is visibly stalled.

  Cadence: a TTY repaints at most every `_TTY_REPAINT_S = 0.1`; a pipe prints an ordinary `log.info`
  line at most every `_LOG_INTERVAL_S = 10.0`. Both are module constants, so a test can drive the
  periodic path without the function growing a parameter nobody asked for. A download that finishes
  inside ten seconds therefore puts ONE line in a CI log, which is the CI ideal, and a long one puts a
  heartbeat in it, which is the point.

  Closing line, both branches: `log.ok(f"{label}  {size} in {duration} ({rate})")`.

- [ ] **Step 6: the arithmetic unit tests**, and only these, over the pure half: 101% is impossible
  when a server over-sends, `total=None` yields no `%`, `elapsed=0` yields no division by zero, a
  20-column terminal yields a 19-character line.

- [ ] **Step 7: verify.** `pytest tests/test_fetch.py -q` green, and paste the four driven outputs
  verbatim into the PR body. A described output is not an output.

---

## Task 3: the three call sites (si#142)

**Files:** `src/simplon/docker.py`, `src/simplon/oras.py`, `src/simplon/pyvenv.py`,
`tests/test_pyvenv.py`

- [ ] **Step 1: `pyvenv.py`.** `urllib.request.urlretrieve(GET_PIP_URL, script)` becomes
  `fetch.download(GET_PIP_URL, script, label="get-pip.py")`. `import urllib.request` is orphaned by
  this change and comes out - and only that; nothing else in the module is touched.

  `tests/test_pyvenv.py` monkeypatches `pyvenv.urllib.request.urlretrieve` at two places; they become
  `pyvenv.fetch.download`. **The signature differs** - `download` returns the path and takes keywords -
  so the doubles change shape, not just name.

- [ ] **Step 2: `oras.py`.** The `# noqa: S310 - a pinned https release asset` comment goes away
  because its argument is now made in code, one level down, for every caller. The `try/finally` that
  unlinks the archive stays exactly as it is.

- [ ] **Step 3: `docker.py`.** Same, plus one deliberate rename: the destination was
  `docker.tgz.part`, a `.part` suffix on what was already the final name. `download` now owns `.part`
  as an internal spelling, so keeping it here would say the opposite of what it means. It becomes
  `docker.tgz`, still unlinked in the same `finally`. `import urllib.request` is orphaned here too.

- [ ] **Step 4: run the three call sites' own suites** - `test_docker.py`, `test_oras.py`,
  `test_pyvenv.py`. Two of the three stub at `_fetch_static_cli` / `_fetch_release` and should be
  untouched; if either turns red, the change was not surgical.

- [ ] **Step 5: drive the cheapest real one.** `pyvenv`'s `get-pip.py` fetch is a real 2 MB https
  download against `bootstrap.pypa.io`. Run `ensure_venv` against a python whose `ensurepip` is
  refused, once in a terminal and once through a pipe, and paste both outputs. This is the step that
  says the wiring is real; the three unit suites only say it is consistent.

---

## Task 4: the public surface (si#142)

**Files:** `src/simplon/surface.py`, `site/content/building/surface.md`

- [ ] **Step 1: classify.** `fetch` goes into `surface.LIBRARY`. It is library by INTENT and the head
  says so without naming anybody: si#142 asks for it to be public precisely so a consuming product uses
  it rather than writing a fourth silent `urlretrieve`. `test_every_top_level_module_is_classified`
  goes red until this exists, which is the mechanism working.

- [ ] **Step 2: check what else the classification drags in.** `test_no_module_is_promised_under_a_task
  _body_s_name` normalises plurals in both directions - there is no `simplon/tasks/fetch.py`, so this
  passes, but check rather than assume. `test_the_website_names_the_same_internals` holds INTERNAL
  only, so a LIBRARY module is not required on the page by any test - which is a reason to write the
  paragraph deliberately rather than a reason to skip it.

- [ ] **Step 3: the page.** `site/content/building/surface.md` describes the second surface with
  `simplon.log`, `simplon.run`, `simplon.host` as its examples. Add `simplon.fetch` there, in one
  sentence that says what it is for and what it refuses, because "you may import it" is not the useful
  half - "it refuses anything but https, times out, and never renames a partial file" is.

- [ ] **Step 4: verify.** `pytest tests/test_surface.py -q` green.

---

## Task 5: the upload half (si#143)

**Files:** `src/simplon/run.py`, `src/simplon/tasks/asset.py`, `tests/test_tasks_asset.py`

**What this task is not.** No Python uploader, no shared upload helper, no bar over `oras push`. simplon
uploads no bytes itself and this task does not make it start.

- [ ] **Step 1: measure the five upload paths rather than trusting the ticket's list.**

  | path | goes through | verdict |
  | --- | --- | --- |
  | `githubpackages` -> `oras push` | `run.stream` | already correct |
  | `tasks/image.py:457` -> `docker push` | `stream` | already correct |
  | `tasks/nuget.py:380` -> `dotnet nuget push` | `stream` | already correct |
  | `tasks/asset.py:84` -> `gh release upload` | `run.run` (capture=True) | **the defect** |
  | `tasks/asset.py:79` -> `gh release create` | `run.run` (capture=True) | **correct as it is** |

  The last row is the one the ticket does not mention and the one that makes the rule a rule rather
  than a preference: `_already_there(created)` reads `"already exists"` out of the captured text to
  tell a lost race from a real failure. That caller INSPECTS the output and reports its own verdict, so
  capturing it is right, and it sits four lines above the call where capturing is wrong.

- [ ] **Step 2: write the rule down once, in `src/simplon/run.py`.** In the module docstring, where
  both `run` and `stream` are in view, with the two rows above as its worked example - a rule stated
  with only the case it fixes reads as a description of that case.

- [ ] **Step 3: write the failing driven test.** Not an assertion over a `capture=` keyword. Put a fake
  `gh` on PATH - a real executable that writes transfer-shaped output - redirect the process's fd 1 and
  2 into a file, call `asset.publish`, and assert the fake's output is IN that file. A subprocess
  writing to an inherited descriptor is the whole mechanism, so that is the thing to observe.

  ```python
  def test_the_upload_tools_own_output_reaches_the_user_rather_than_a_variable(tmp_path, ...):
      """si#143. `gh release upload` is a transfer the user is waiting on, and capture=True is the
      kernel deciding on their behalf that they may not watch it."""
  ```

  And the half the ticket warns about, because a step that stops capturing can stop saying why:

  ```python
  def test_a_failed_upload_still_says_what_went_wrong(...):
      """The trade this must NOT make: one silence for another."""
  ```

- [ ] **Step 4: watch both fail.** The first on the output being absent from the file; the second, once
  the switch is made, on the error text.

- [ ] **Step 5: implement.** `run.stream` for the upload. `run_stream` was considered and REJECTED, and
  the reason belongs in the commit: it pipes, and a tool that sees a pipe turns its own progress
  rendering off - so the one function that would give live output AND a captured reason gives neither.
  `capture=False` inherits the real descriptors, which is the only arrangement in which `gh` renders
  anything at all.

  The failure message therefore follows `image.py` and `nuget.py`, which already solved this: name the
  rc and point at the output that is directly above it, rather than quoting text the kernel no longer
  holds. `_said` stays, because the create path still uses it.

- [ ] **Step 6: repair `test_an_upload_that_failed_is_not_reported_as_a_publication`,** which matches
  `"422"` out of a message that no longer carries it. It becomes an assertion that the failure is
  raised and names the release and the rc - the property it was really protecting - and the new test
  from Step 3 covers the reason reaching the user.

- [ ] **Step 7: drive it for real.** `gh release upload` against a repository that does not exist, so
  nothing is created anywhere, and confirm with fd 1 not captured that `gh`'s own error text appears on
  the terminal and the `RuntimeError` still names the tag. Paste both.

---

## Task 6: the gates, and a reviewer

- [ ] **Step 1:** `./simplon.sh test typecheck-python` - `Success`, and the file count is 85, not 84,
  because a new module that mypy is not looking at is not covered by the gate.
- [ ] **Step 2:** `./simplon.sh test all` - the same four pre-existing failures and no others.
  A fifth is this branch's, whatever its name says.
- [ ] **Step 3:** `tests/test_refusal_census.py` in particular. `DownloadError` is a new `raise` in the
  kernel; the census walks out from the two manifest seams, and nothing reaches `fetch` from either, so
  it should be outside the population. Confirm that rather than assume it - if the walk does reach it,
  the answer is a census entry, not a weakened walk.
- [ ] **Step 4:** dispatch `python-reviewer` on the diff and act on what it finds.
