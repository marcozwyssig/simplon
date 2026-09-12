@gate
Feature: One command reaches one verdict

  The local gate and the pipeline have to be the same command, or the two drift and the next divergence
  is found by whoever has the least context. These scenarios walk that claim from outside: what a
  developer types and what CI types reach the same body, and a step that found nothing is never green.

  Background:
    Given a clean checkout of simplon

  Scenario: The local gate runs every test the pipeline runs
    When I run "./simplon.sh test all"
    Then the run reports the pytest suite, the type gate and the release-notes guard
    And every leaf named in ".github/workflows/ci.yml" was one of them

  Scenario Outline: A failing <leaf> turns the aggregate red
    Given the <leaf> step is made to fail
    When I run "./simplon.sh test all"
    Then the run exits non-zero
    And the summary names <leaf> as the step that failed
    And the other steps still ran and still printed their own verdict

    Examples:
      | leaf            |
      | suite           |
      | typecheck-python|
      | release-notes   |

  Scenario: A gate that found nothing to run is not green
    Given a suite directory holding no test at all
    When the gate for it runs
    Then the run does not report success
    And the message says that nothing was collected rather than that nothing failed
