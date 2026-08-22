"""The Invoke behaviours the task generator depends on (netctl#1434).

Measured against Invoke 3.0.3 during design. Each assertion here is a DECISION the generator makes, so a
version bump that changes one of them must fail HERE rather than inside a rendered module, where the
symptom would appear far from its cause. AAA throughout.
"""
from invoke import Collection, Task
from invoke.parser import Parser, ParserContext


def _body(c, sites="all", dry_run=False):
    """Seed the lab and run the smoke test."""
    return (sites, dry_run)


def test_a_runtime_built_task_exposes_its_signature_as_arguments():
    # arrange / act: this is what makes `with:`-key validation and per-task --help claims real
    args = Task(_body, name="seed").get_arguments()

    # assert
    assert [(a.name, a.default) for a in args] == [("sites", "all"), ("dry_run", False)]


def test_a_runtime_built_task_parses_like_a_decorated_one():
    # arrange
    task = Task(_body, name="seed")

    # act
    result = Parser(initial=ParserContext(),
                    contexts=[ParserContext(name="seed", args=task.get_arguments())]
                    ).parse_argv(["seed", "--sites", "zh", "--dry-run"])

    # assert
    parsed = {k: v.value for c in result if c.name for k, v in c.args.items()}
    assert parsed == {"sites": "zh", "dry-run": True}


def test_one_body_can_back_two_tasks_with_their_own_names_and_help():
    # arrange: the generator renders one wrapper per DECLARATION, so a shared body must not alias
    first = Task(_body, name="seed", help={"sites": "which sites"})
    second = Task(_body, name="seed-zh", help={"sites": "pinned to zh"})

    # act
    ns = Collection("lab")
    ns.add_task(first)
    ns.add_task(second)

    # assert
    assert sorted(ns.task_names) == ["seed", "seed-zh"]
    assert first.help["sites"] != second.help["sites"]


def test_invoke_has_no_task_level_passthrough():
    # arrange: a variadic body is the obvious way to pass raw args through, and it does not work - which
    # is WHY the facade bypasses the parser for passthrough_args commands (design section 5.4).
    def variadic(c, *args):
        """Run gradle."""
        return args

    task = Task(variadic, name="gradle")

    # act: one positional IS collected
    ok = Parser(initial=ParserContext(),
                contexts=[ParserContext(name="gradle", args=task.get_arguments())]
                ).parse_argv(["gradle", ":web:bootTest"])

    # assert
    assert [c for c in ok if c.name][0].args["args"].value == ":web:bootTest"

    # act / assert: a flag is a hard parse error
    try:
        Parser(initial=ParserContext(),
               contexts=[ParserContext(name="gradle", args=task.get_arguments())]
               ).parse_argv(["gradle", ":web:bootTest", "--rerun-tasks"])
    except Exception as exc:
        assert "rerun-tasks" in str(exc)
    else:
        raise AssertionError("expected a parse error; Invoke gained task-level passthrough - revisit "
                             "design section 5.4, the facade bypass may no longer be needed")
