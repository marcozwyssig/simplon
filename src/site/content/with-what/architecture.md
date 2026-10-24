---
title: "Architecture"
weight: 7
---

GENERATED from `src/firn/model/simplon/components/components.firn` by `./simplon.sh build model` (si#390).

Every module of `src/simplon/` belongs to one component. An import may stay inside its component or go
to a component on a lower layer; two components on the same layer do not import each other. Any other
import is a named exception below, with the ticket that resolves it. `src/tests/test_architecture.py`
holds the code to this page.

The test reads Python imports only. A body named by text - a product's `impl: "module:function"`, or the
generated task class a catalogue coordinate names - is resolved at run time, and no layer applies to it.

| Layer | Component | What it is for |
|---|---|---|
| 0 | `kernel` | Running a plan: steps, outcomes, the subprocess seam, the log. |
| 1 | `model` | The vocabulary a pipeline is said in: the task and command base classes, the artifact schema and the carrier spec. It imports nothing outside itself. |
| 2 | `manifest` | Reading the configuration, validating it, and building the plan from it. |
| 3 | `adapters` | The tools and platforms a task drives: docker, oras, a registry, a lab, a proxy. |
| 4 | `tasks` | The catalogue's task bodies, and the generators they call. |
| 6 | `cli` | The command line: simplon and simplon init, and what a product may import. |
| 5 | `ui` | Running a plan in front of a person. |

## kernel

`kernel.steps`, `kernel.product`, `kernel.plan`, `kernel.run`, `kernel.awake`, `kernel.provenance`, `kernel.runhost`, `kernel.log`, `kernel.verdict`, `kernel.steplog`, `kernel.waits`, `kernel.degraded`, `kernel.filelock`, `kernel.moved`

## model

`model.command`, `model.artifactschema`, `model.carrierspec`, `model.task`

## manifest

`manifest.load`, `manifest.treeform`, `manifest.yamlkeys`, `manifest.artifactsection`, `manifest.ports`, `manifest.results`, `manifest.environments`, `manifest.layout`, `manifest.launcherenv`, `manifest.outputs`, `manifest.deployment`, `manifest.signatures`, `manifest.context`, `manifest.catalogue`, `manifest.runners`, `manifest.manifestmodel`, `manifest.clitaxonomy`

## adapters

`adapters.backend`, `adapters.brew`, `adapters.checksum`, `adapters.clablifecycle`, `adapters.clabrender`, `adapters.compose`, `adapters.credentials`, `adapters.devcontainer`, `adapters.disk`, `adapters.diskguard`, `adapters.docker`, `adapters.fetch`, `adapters.gh`, `adapters.github`, `adapters.githubpackages`, `adapters.healthgate`, `adapters.host`, `adapters.hostinstall`, `adapters.hostpath`, `adapters.imagenames`, `adapters.interact`, `adapters.labegress`, `adapters.labhost`, `adapters.labinstance`, `adapters.labnet`, `adapters.linux`, `adapters.nexusproxy`, `adapters.oras`, `adapters.portainer`, `adapters.ports`, `adapters.pypi`, `adapters.pyvenv`, `adapters.repofile`, `adapters.tools`, `adapters.topology`, `adapters.tracker`

## tasks

`tasks.completiongen`, `tasks.taskgen`, `tasks.acceptance`, `tasks.allure`, `tasks.artifact`, `tasks.asset`, `tasks.buildfiles`, `tasks.carrier`, `tasks.ciarm64`, `tasks.cidisk`, `tasks.ciprivileges`, `tasks.claudemd`, `tasks.claudeplugins`, `tasks.cliref`, `tasks.completion`, `tasks.conan`, `tasks.deploy`, `tasks.docs`, `tasks.fetchfile`, `tasks.firngen`, `tasks.env`, `tasks.generated`, `tasks.gitops`, `tasks.handoff`, `tasks.hosttools`, `tasks.image`, `tasks.manifestcheck`, `tasks.manifestmodel`, `tasks.maven`, `tasks.migrate`, `tasks.nexus`, `tasks.nuget`, `tasks.profiles`, `tasks.proxmoxapi`, `tasks.release`, `tasks.githubrelease`, `tasks.homebrewformula`, `tasks.releasenotes`, `tasks.site`, `tasks.taskverbs`, `tasks.testrun`, `tasks.toolchain`, `tasks.typecheck`, `tasks.vcs`, `tasks.walk`, `tasks.workflows`, `tasks.workflowgen`, and one generated class per catalogue task: `tasks.build_image`, `tasks.build_fetch`, `tasks.test_image`, `tasks.release_image`, `tasks.release_artifact`, `tasks.build_conan_cache`, `tasks.release_conan`, `tasks.build_nuget_config`, `tasks.build_nuget_restore`, `tasks.build_nuget_pack`, `tasks.release_nuget`, `tasks.build_maven_pack`, `tasks.release_maven`, `tasks.release_notes`, `tasks.release_tag`, `tasks.release_github_unpublished`, `tasks.release_github_draft`, `tasks.release_github_publish`, `tasks.docs_site`, `tasks.deploy_up`, `tasks.toolchain_run`, `tasks.vcs_commit`, `tasks.vcs_push`, `tasks.vcs_prune_branches`, `tasks.vcs_auth_scopes`, `tasks.vcs_submodules`, `tasks.support_ci_privileges`, `tasks.support_ci_disk_hygiene`, `tasks.support_ci_arm64`, `tasks.support_ci_disk_preflight`, `tasks.support_ci_disk_cleanup`, `tasks.test_gate`, `tasks.test_typecheck_python`, `tasks.test_generated`, `tasks.test_release_notes`, `tasks.test_report`, `tasks.test_accept`, `tasks.test_walk`, `tasks.support_nexus`, `tasks.support_install`, `tasks.support_claude_plugins`, `tasks.support_claude_md`, `tasks.support_environments`, `tasks.support_completion`, `tasks.support_workflows`, `tasks.docs_render`, `tasks.docs_reference`, `tasks.docs_acceptance`, `tasks.build_model`, `tasks.build_cmake_files`, `tasks.build_dotnet_solution`, `tasks.deploy_carrier`, `tasks.deploy_down`, `tasks.release_asset`, `tasks.tasks_generate`, `tasks.tasks_catalogue`, `tasks.support_migrate`, `tasks.test_manifest_model`, `tasks.support_model`, `tasks.support_toolchain`

## cli

`cli.__init__`, `cli.bootstrap`, `cli.surface`

## ui

`ui.clipboard`, `ui.tui`

## Exceptions

| Import | Why | Ticket |
|---|---|---|
<!-- Generated by firn, do not edit outside protected regions. id=[ArchitecturePage:,c4ba194e13164bc8] -->
