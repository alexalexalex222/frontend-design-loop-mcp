# Release checklist

This local upgrade is not published. Publication, registry updates, commits, and
pushes require separate user authorization. This checklist grants none.

Before a release:

- Align package/runtime/registry/changelog version metadata. The local upgrade is
  consistently marked 1.1.0; this does not establish a published release.
- Run focused setup/toolkit, provider/runtime, evidence, and automated-loop tests.
- Build wheel/sdist and install the wheel into a fresh local environment.
- Verify both installed console entrypoints and packaged playbook resources.
- Verify native-only installation imports without Google or retry cloud extras;
  selecting a cloud provider should explain the required `[cloud]` extra.
- Run real desktop/mobile preview capture and interaction assertions; verify
  returned MCP images, durable manifests, tree cleanup, and skipped/error semantics.
- Run Windows/macOS/Linux checks; report unknown hosted-platform results explicitly.
- Keep live CLI auth/inference opt-in and distinguish installation, authentication,
  route verification, requested/observed model/effort, and actual inference.
- Verify printed configs parse with Windows paths and preserve unrelated user settings
  under explicit installation. Check an invalid config remains intact.
- Review documentation against final integrated behavior. Published PyPI installation
  instructions must identify which release actually includes the upgrade.
- Check no claims of universal visual improvement or human preference are inferred
  from screenshots, model scores, or successful mechanical checks.

After separately authorized publication, verify the published installation in a new
environment and update directory submission copy to match the released tool surface.
