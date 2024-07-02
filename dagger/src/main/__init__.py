"""A generated module for BalanceR functions

This module has been generated via dagger init and serves as a reference to
basic module structure as you get started with Dagger.
"""

import dagger
from dagger import dag, function, object_type


@object_type
class BalanceR:

    @function
    def chuck_norris(self, source: dagger.Directory, python: str = ""):
        """Run lint and test (WITHOUT FAILING, EVER!)"""
        self.test(source, python)
        self.lint(source, python)


    @function
    async def test(self, source: dagger.Directory, python: str = "") -> str:
        """Return the result of running unit tests"""
        return await (
            self.build_env(source, python)
            .with_exec(["pip", "install", "pytest"])
            .with_exec(["pytest", "balancer_test.py"])
            .stdout()
        )

    @function
    async def lint(self, source: dagger.Directory, python: str = "") -> str:
        """Return the result of the linting"""
        return await (
            self.build_env(source, python)
            .with_exec(["pip", "install", "flake8"])
            .with_exec(["flake8", "balancer.py", "--count", "--select=E9,F63,F7,F82", "--show-source", "--statistics"])
            .with_exec(["flake8", "balancer.py", "--count", "--exit-zero", "--max-complexity=10", "--max-line-length=127", "--statistics"])
            .stdout()
        )

    @function
    def build_env(self, source: dagger.Directory, python: str = "") -> dagger.Container:
        """Build a ready-to-use development environment"""
        python_version = python if python != "" else "3"
        return (
            dag.container()
            .from_("python:"+python_version+"-alpine")
            .with_directory("/src", source)
            .with_workdir("/src")
            .with_exec(["pip", "install", "--upgrade", "pip"])
            .with_exec(["pip", "install", "-r", "requirements.txt"])
        )

    @function
    def publish(self, source: dagger.Directory, target: str, registry: str, username: str, password: dagger.Secret) -> str:
        """Publish image"""
        return (
            self.build_app_container(source)
            .with_registry_auth(registry, username, password)
            .publish(target)
        )

    @function
    def build_app_container(self, source: dagger.Directory) -> dagger.Container:
        """Build the app container"""
        return (
            dag.container()
            .with_directory("/src", source)
            .with_workdir("/src")
            .directory("/src")
            .docker_build()
        )