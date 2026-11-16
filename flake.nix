{
  description = "dir3 - das Leben zeitlich programmieren, weich und anker-basiert";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f (import nixpkgs { inherit system; }));

      # Android SDK/build outputs and the local recipe DB must never enter
      # the Nix store (hundreds of MB that are not part of the package).
      projectSrc = nixpkgs.lib.cleanSourceWith {
        src = ./.;
        filter = path: type:
          let name = baseNameOf path; in
          !(builtins.elem name [
            ".git" ".android-sdk" ".venv" ".gradle" "build" "data"
            "__pycache__" ".pytest_cache" ".ruff_cache" "node_modules" "result"
          ]);
      };

      pyProject = {
        pname = "dir3";
        version = "0.1.0";
        src = projectSrc;
        pyproject = true;
        nativeBuildInputs = [ ];
        propagatedBuildInputs = [ ];
        # Python version selection done inside devShell/package below.
      };

      # aiogoogle is not in nixpkgs yet - packaged here from PyPI.
      aiogoogleFor = pkgs: pkgs.python3.pkgs.buildPythonPackage rec {
        pname = "aiogoogle";
        version = "5.19.0";
        pyproject = true;
        build-system = [ pkgs.python3.pkgs.setuptools ];
        src = pkgs.fetchPypi {
          inherit pname version;
          hash = "sha256-lpTlmhHUc5I2+6g3BxoXrtNwjhujjzBD2QBCaxFnfi8=";
        };
        propagatedBuildInputs = with pkgs.python3.pkgs; [
          aiofiles
          aiohttp
          async-timeout
          google-auth
        ];
        doCheck = false;
        meta.description = "Async Google API client";
      };
    in
    {
      packages = forAllSystems (pkgs:
        let
          pypkgs = pkgs.python3.pkgs;
        in
        {
          default = pypkgs.buildPythonPackage (pyProject // {
            nativeBuildInputs = with pypkgs; [ setuptools wheel ];
            propagatedBuildInputs = with pypkgs; [
              requests
              tzdata
              httpx
              hijridate
              (aiogoogleFor pkgs)
            ];
            checkInputs = with pypkgs; [ pytest pytestCheckHook holidays ];
          });
        });

      devShells = forAllSystems (pkgs:
        let
          pypkgs = pkgs.python3.pkgs;
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              python3
              pypkgs.requests
              pypkgs.tzdata
              pypkgs.httpx
              pypkgs.hijridate
              (aiogoogleFor pkgs)
              pypkgs.pytest
              pypkgs.ruff
              pypkgs.holidays
              self.packages.${system}.default
            ];
            shellHook = ''
              export PYTHONPATH="${toString ./src}:$PYTHONPATH"
            '';
          };
        });
    };
}