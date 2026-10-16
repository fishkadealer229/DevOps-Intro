{
  description = "QuickNotes — reproducible Go build + deterministic OCI image (DevOps-Intro Lab 11)";

  # nixos-25.11 ships Go >= 1.24, which app/go.mod requires. The channel name
  # here is only a hint: flake.lock pins the exact revision and its narHash, so
  # every clone gets byte-identical nixpkgs.
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";

  outputs = { self, nixpkgs }:
    let
      # Only systems that can actually be built here. Leaving aarch64 out is
      # deliberate: `nix flake check` tries to *build* every system listed, so
      # advertising aarch64 without an aarch64 builder turns `nix flake check`
      # red for a reason that has nothing to do with reproducibility. Add it
      # (plus a remote builder or an aarch64 host) if you actually need it.
      systems = [ "x86_64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f system);
      version = "0.1.0";
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          inherit (pkgs) lib;

          # ------------------------------------------------------------------
          # Task 1 — the Go binary.
          #
          # buildGoModule (not buildGoApplication): QuickNotes is a plain
          # single-module Go project with a go.mod and no dependencies, which is
          # exactly buildGoModule's sweet spot. buildGoApplication (gomod2nix)
          # targets multi-module / workspace layouts and needs an extra
          # generated file, which would add a moving part for no benefit here.
          # See submissions/lab11.md, question (d).
          # ------------------------------------------------------------------
          quicknotes = pkgs.buildGoModule {
            pname = "quicknotes";
            inherit version;
            src = ./app;

            # Static binary: no libc dependency, so it runs on distroless/scratch.
            #
            # Passed through `env`, NOT as a top-level argument. buildGoModule in
            # nixpkgs 25.11 builds `env` itself and rejects overlapping names:
            #
            #   error: The `env` attribute set cannot contain any attributes
            #   passed to derivation. The following attributes are overlapping:
            #     - CGO_ENABLED: in `env`: 1; in derivation arguments: 0
            #
            # so the classic `CGO_ENABLED = 0;` spelling no longer evaluates.
            env = {
              CGO_ENABLED = 0;
            };

            # -s -w strips the symbol table and DWARF (carried from Lab 6).
            #
            # Two further sources of non-determinism are already handled by
            # buildGoModule, so they must NOT be set here:
            #   * it adds `-trimpath` to GOFLAGS unless allowGoReference = true,
            #     which removes the absolute build directory from the binary;
            #   * it appends `-buildid=` to ldflags unless a buildid is given,
            #     because the Go build ID is otherwise environment-dependent.
            # (nixpkgs: pkgs/build-support/go/module.nix — the GOFLAGS and
            #  ldflags blocks. There is no `trimpath` argument to pass.)
            ldflags = [ "-s" "-w" ];

            # vendorHash is the SRI hash of the output of `go mod vendor` — that
            # is, of the vendored dependency tree ONLY; the implementation is
            # `cp -r vendor $out`. QuickNotes declares no dependencies, so that
            # tree is empty, and nixpkgs documents `null` as the correct value
            # for exactly this case:
            #
            #   # The SRI hash of the vendored dependencies.
            #   # If `null`, it means the project either has no external
            #   # dependencies or the vendored dependencies are already present
            #   # in the source tree.
            #
            # A hash here would not merely be unnecessary, it would be wrong:
            # the derivation aborts with "vendor folder is empty, please set
            # 'vendorHash = null;' in your expression". `null` also skips the
            # fixed-output derivation entirely (goModules = ""), so this build
            # needs no network at all.
            vendorHash = null;

            meta = {
              description = "QuickNotes API — a tiny notes service";
              homepage = "https://github.com/fishkadealer229/DevOps-Intro";
              license = lib.licenses.mit;
              mainProgram = "quicknotes";
            };
          };

          # ------------------------------------------------------------------
          # Task 2 — deterministic OCI image, built without Docker.
          #
          # dockerTools.buildImage writes fixed timestamps and stable layer
          # ordering instead of "now" and filesystem iteration order, which is
          # what makes the tarball digest reproducible.
          # ------------------------------------------------------------------
          docker = pkgs.dockerTools.buildImage {
            name = "quicknotes";
            tag = "v${version}";

            copyToRoot = pkgs.buildEnv {
              name = "image-root";
              paths = [ quicknotes ];
              pathsToLink = [ "/bin" ];
            };

            # Runs before copyToRoot is unpacked, so this is where the writable
            # state directory and the seed file come from.
            #   /tmp  -> mode 1777, world-writable, so the nonroot uid can
            #            persist notes without the image needing a chown.
            #   /app  -> read-only seed data baked in, like the Lab 6 image.
            extraCommands = ''
              mkdir -p -m 1777 tmp
              mkdir -p app
              cp ${./app/seed.json} app/seed.json
            '';

            config = {
              # exec form: the binary is PID 1, no shell involved.
              Entrypoint = [ "/bin/quicknotes" ];
              ExposedPorts = { "8080/tcp" = { }; };

              # Lab 6 discipline carried forward: never run as root.
              User = "65532:65532";
              WorkingDir = "/";

              Env = [
                "ADDR=:8080"
                "DATA_PATH=/tmp/notes.json"
                "SEED_PATH=/app/seed.json"
              ];

              Labels = {
                "org.opencontainers.image.title" = "quicknotes";
                "org.opencontainers.image.version" = "v${version}";
                "org.opencontainers.image.source" = "https://github.com/fishkadealer229/DevOps-Intro";
                "org.opencontainers.image.licenses" = "MIT";
              };
            };
          };
        in
        {
          inherit quicknotes docker;
          default = quicknotes;
        });

      # ----------------------------------------------------------------------
      # `nix develop` drops collaborators into a shell with the toolchain the
      # project actually uses, so a fresh clone needs no manual Go install.
      # ----------------------------------------------------------------------
      devShells = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              go
              gopls
              golangci-lint
            ];

            shellHook = ''
              echo "QuickNotes dev shell"
              echo "  go            $(go version | cut -d' ' -f3)"
              echo "  build         nix build .#quicknotes"
              echo "  image         nix build .#docker"
            '';
          };
        });

      # `nix flake check` builds everything in `checks`, so the flake has a real
      # self-test instead of a no-op: a broken derivation fails the check rather
      # than silently passing.
      checks = forAllSystems (system: {
        inherit (self.packages.${system}) quicknotes docker;
      });
    };
}
