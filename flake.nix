{
  description = "dir3 - das Leben zeitlich programmieren, weich und anker-basiert";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f (import nixpkgs { inherit system; }));

      pyProject = {
        pname = "dir3";
        version = "0.1.0";
        src = ./.;
        pyproject = true;
        nativeBuildInputs = [ ];
        propagatedBuildInputs = [ ];
        # Python version selection done inside devShell/package below.
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
            propagatedBuildInputs = with pypkgs; [ requests tzdata httpx ];
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