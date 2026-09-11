// The Hugo module file for Simplon's documentation website.
//
// It is COMMITTED rather than generated on the fly, for two reasons. `hugo mod get` needs a module file
// to write into - without one it stops before it starts - and the version it writes has to come from
// somewhere a human chose. The theme pin in ../simplon.yaml is that choice; `docs:site` runs
// `hugo mod get <module>@<version>` with it before every build, so this file is rewritten to agree with
// the manifest on every run.
//
// That rewrite is idempotent when the two already agree, which is the normal state - but it is still a
// WRITE into the working tree, and `hugo mod get` also refreshes go.sum. A CI job that builds the site
// and then asserts a clean working tree will see a diff the first time the manifest pin moves ahead of
// this file. That is the mechanism working, not a fault; the publishing job must not gate on it.
module github.com/marcozwyssig/simplon/site

go 1.24

require github.com/imfing/hextra v0.12.3 // indirect
