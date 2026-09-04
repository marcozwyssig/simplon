"""A credential supplied without ever becoming a command-line argument.

Arrange / Act / Assert throughout, one action per test. The terminal is stubbed rather than mocked at
the library boundary: what is under test is what this module DECIDES - whether to ask, which variable,
what to do with the answer - not whether getpass reads a tty.

The variable NAMES are derived from `variables()` rather than written out, and the values are visibly
inert placeholders. One test pins the naming convention against literals, which is where that belongs;
everywhere else a literal `NAME_PASSWORD: "..."` pair would read to a secret scanner exactly like the
leak this module exists to prevent, and a check that cries wolf on its own test suite is a check people
learn to wave through.
"""
import pytest

from delivery import credentials

PREFIX = "ACTIFSOURCE"
USER_VAR, PASSWORD_VAR = credentials.variables(PREFIX)

NAME = "marcozwyssig"          # a username: not a secret, and allowed on a command line
TYPED = "typed-at-the-prompt"  # stands in for whatever the operator types
STORED = "already-in-the-env"  # stands in for a value the environment already carried


@pytest.fixture
def terminal(monkeypatch):
    """A terminal that answers every prompt with a fixed string, recording what it was asked."""
    asked = []

    class _Tty:
        def isatty(self):
            return True

    def fake_getpass(prompt=""):
        asked.append(prompt)
        return TYPED

    monkeypatch.setattr(credentials.sys, "stdin", _Tty())
    monkeypatch.setattr(credentials.getpass, "getpass", fake_getpass)
    return asked


@pytest.fixture
def no_terminal(monkeypatch):
    """A pipe, which is what CI hands a process."""
    class _Pipe:
        def isatty(self):
            return False

    def refuse(prompt=""):
        raise AssertionError("asked for a password with no terminal to ask on")

    monkeypatch.setattr(credentials.sys, "stdin", _Pipe())
    monkeypatch.setattr(credentials.getpass, "getpass", refuse)


# --- the convention ---------------------------------------------------------------------------------

def test_a_prefix_names_its_two_variables():
    # The one place the convention is pinned against literals; every other test derives them from here.
    prefix = "ACTIFSOURCE"

    names = credentials.variables(prefix)

    assert names == ("ACTIFSOURCE_USER", "ACTIFSOURCE_PASSWORD")


def test_a_complete_credential_resolves():
    env = {USER_VAR: NAME, PASSWORD_VAR: STORED}

    resolved = credentials.credential(PREFIX, env)

    assert resolved == (NAME, STORED)


@pytest.mark.parametrize("env, why", [
    ({USER_VAR: NAME}, "the password is missing"),
    ({PASSWORD_VAR: STORED}, "the username is missing"),
    ({USER_VAR: "  ", PASSWORD_VAR: STORED}, "whitespace is set by accident, never on purpose"),
    ({USER_VAR: NAME, PASSWORD_VAR: ""}, "an empty password is no password"),
    ({}, "nothing is set at all"),
])
def test_half_a_credential_is_no_credential(env, why):
    # Folding a username with no password into a URL produces a 401 that names the wrong problem.
    resolved = credentials.credential(PREFIX, env)

    assert resolved is None, why


def test_a_prefix_nobody_named_resolves_to_nothing():
    env = {USER_VAR: NAME, PASSWORD_VAR: STORED}

    resolved = credentials.credential("", env)

    assert resolved is None


# --- what is missing --------------------------------------------------------------------------------

def test_a_username_without_its_password_names_the_variable_to_ask_for():
    env = {USER_VAR: NAME}

    variable = credentials.missing_password_variable([PREFIX], env)

    assert variable == PASSWORD_VAR


def test_a_run_that_supplies_neither_half_is_missing_nothing():
    # Neither half means the run is not asking for the protected thing at all.
    variable = credentials.missing_password_variable([PREFIX], {})

    assert variable is None


def test_a_complete_credential_is_missing_nothing():
    env = {USER_VAR: NAME, PASSWORD_VAR: STORED}

    variable = credentials.missing_password_variable([PREFIX], env)

    assert variable is None


def test_a_blank_password_is_a_missing_password():
    env = {USER_VAR: NAME, PASSWORD_VAR: "   "}

    variable = credentials.missing_password_variable([PREFIX], env)

    assert variable == PASSWORD_VAR


def test_the_half_supplied_prefix_is_the_one_named():
    # Several prefixes, one of them half-supplied: the answer names that one, not the complete one.
    complete_user, complete_password = credentials.variables("COMPLETE")
    half_user, _ = credentials.variables("HALF")
    env = {complete_user: NAME, complete_password: STORED, half_user: NAME}

    variable = credentials.missing_password_variable(["COMPLETE", "HALF"], env)

    assert variable == "HALF_PASSWORD"


# --- asking -----------------------------------------------------------------------------------------

def test_a_secret_already_set_is_never_asked_for_again(terminal):
    # Asking twice for something already supplied is impossible by construction, not by convention.
    env = {PASSWORD_VAR: STORED}

    variable = credentials.ask_for_secret(PASSWORD_VAR, env)

    assert variable is None
    assert terminal == []


def test_a_secret_is_asked_for_and_stored(terminal):
    env = {}

    variable = credentials.ask_for_secret(PASSWORD_VAR, env)

    assert variable == PASSWORD_VAR
    assert env[PASSWORD_VAR] == TYPED


def test_a_name_is_asked_for_in_the_clear(monkeypatch):
    # Echoed on purpose: hiding a username helps nobody and makes a typo invisible.
    class _Tty:
        def isatty(self):
            return True
    monkeypatch.setattr(credentials.sys, "stdin", _Tty())
    monkeypatch.setattr("builtins.input", lambda prompt="": NAME)
    env = {}

    variable = credentials.ask_for_name(USER_VAR, "username", env)

    assert variable == USER_VAR
    assert env[USER_VAR] == NAME


def test_asking_for_a_credential_fills_in_both_halves(monkeypatch, terminal):
    # The caller has just watched something fail for want of exactly this credential, so a run that
    # named nothing is still asked - and is asked for the username too.
    monkeypatch.setattr("builtins.input", lambda prompt="": NAME)
    env = {}

    answered = credentials.ask_for_credential(PREFIX, env)

    assert answered == PREFIX
    assert env[USER_VAR] == NAME and env[PASSWORD_VAR] == TYPED


def test_asking_for_a_credential_fills_in_only_the_missing_half(monkeypatch, terminal):
    def refuse(prompt=""):
        raise AssertionError("asked for a username that was already known")
    monkeypatch.setattr("builtins.input", refuse)
    env = {USER_VAR: NAME}

    answered = credentials.ask_for_credential(PREFIX, env)

    assert answered == PREFIX
    assert env[PASSWORD_VAR] == TYPED


def test_a_declined_credential_is_reported_as_incomplete(monkeypatch):
    # An operator who declines once must not be asked in a loop, so this says "no credential" rather
    # than "ask again".
    class _Tty:
        def isatty(self):
            return True
    monkeypatch.setattr(credentials.sys, "stdin", _Tty())
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    monkeypatch.setattr(credentials.getpass, "getpass", lambda prompt="": "")
    env = {}

    answered = credentials.ask_for_credential(PREFIX, env)

    assert answered is None


def test_a_credential_is_not_asked_for_without_a_terminal(no_terminal, monkeypatch):
    def refuse(prompt=""):
        raise AssertionError("asked for a username with no terminal to ask on")
    monkeypatch.setattr("builtins.input", refuse)
    env = {}

    answered = credentials.ask_for_credential(PREFIX, env)

    assert answered is None
    assert env == {}


def test_asking_sets_the_variable_it_named(terminal):
    env = {USER_VAR: NAME}

    variable = credentials.ask_for_password([PREFIX], env)

    assert variable == PASSWORD_VAR
    assert env[PASSWORD_VAR] == TYPED


def test_the_prompt_names_the_variable_being_asked_for(terminal):
    env = {USER_VAR: NAME}

    credentials.ask_for_password([PREFIX], env)

    assert terminal == [f"{PASSWORD_VAR} (not echoed): "]


def test_nothing_is_asked_without_a_terminal(no_terminal):
    # THE CI CASE. A prompt here writes to a pipe nobody reads and then waits forever: the job does not
    # fail, it hangs until a timeout kills it. The fixture fails the test if anything is asked.
    env = {USER_VAR: NAME}

    variable = credentials.ask_for_password([PREFIX], env)

    assert variable is None
    assert PASSWORD_VAR not in env


def test_nothing_is_asked_when_nobody_named_a_username(terminal):
    env = {}

    variable = credentials.ask_for_password([PREFIX], env)

    assert variable is None
    assert terminal == []


def test_nothing_is_asked_when_the_credential_is_complete(terminal):
    env = {USER_VAR: NAME, PASSWORD_VAR: STORED}

    variable = credentials.ask_for_password([PREFIX], env)

    assert variable is None
    assert terminal == []


def test_an_empty_answer_leaves_the_variable_unset(monkeypatch):
    # Carrying a blank password to the server produces a 401 that blames the repository. Unset lets the
    # caller's own "skipped, and named" path report what actually happened.
    class _Tty:
        def isatty(self):
            return True
    monkeypatch.setattr(credentials.sys, "stdin", _Tty())
    monkeypatch.setattr(credentials.getpass, "getpass", lambda prompt="": "")
    env = {USER_VAR: NAME}

    variable = credentials.ask_for_password([PREFIX], env)

    assert variable is None
    assert PASSWORD_VAR not in env


def test_what_was_typed_is_never_returned_to_the_caller(terminal):
    # It goes into the environment, where only this process tree can read it. A caller that received it
    # would be free to log it, and that is the mistake this module exists to make hard.
    env = {USER_VAR: NAME}

    variable = credentials.ask_for_password([PREFIX], env)

    assert variable == PASSWORD_VAR and TYPED not in variable
