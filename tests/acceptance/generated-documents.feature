@documents
Feature: The generated documents cannot go stale

  Simplon publishes two pages it never writes by hand: the command reference, read off the assembled
  command line, and this acceptance document, read off these very files. Both exist because a
  hand-maintained list goes stale silently - a command is added, a scenario is added, and nothing
  anywhere goes red. These scenarios are how somebody confirms that from outside the code.

  Background:
    Given a clean checkout of simplon
    And docker is available to the caller

  @reference
  Scenario: The command reference names every command the assembled CLI offers
    When I run "./simplon.sh build reference"
    Then "docs/site/content/with-what/commands.md" exists
    And every command "./simplon.sh --help" lists has a section on that page
    And the page's own lead sentence states the number of commands it documents

  @acceptance
  Scenario: The acceptance document names every scenario the feature files carry
    When I run "./simplon.sh build acceptance"
    Then "docs/site/content/with-what/acceptance.md" exists
    And every scenario title in "tests/acceptance" appears on that page
    And each one is addressed by its feature file and its title, separated by a colon

  @acceptance @growth
  Scenario: A new scenario reaches the page without anybody editing the page
    Given the acceptance document has been generated once
    When I add a scenario to any file under "tests/acceptance"
    And I run "./simplon.sh build acceptance" again
    Then the page carries the new scenario
    And the count in its lead sentence has grown by one
    And no file under "docs/site/content" was edited by hand

  @site
  Scenario: Both pages reach the published website
    When I run "./simplon.sh build docs"
    Then "build/website/with-what/commands/index.html" exists
    And "build/website/with-what/acceptance/index.html" exists
