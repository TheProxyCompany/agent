from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import logging
import os
from collections.abc import Callable
from typing import Any

from mcp.types import Tool as MCPTool
from pse.types.json.schema_sources.from_function import callable_to_schema
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class Tool:
    """A tool is a piece of code that can be invoked by an agent."""

    def __init__(
        self,
        name: str,
        description: str,
        callable: Callable | None = None,
        schema: dict[str, Any] | None = None,
        mcp_server: str | None = None,
    ):
        self.name = name
        self.description = description
        self.schema = schema
        self.callable = callable
        self.mcp_server = mcp_server
        if callable:
            self.source_code = inspect.getsource(callable)
            self.schema = callable_to_schema(callable)

    async def call(self, caller: Any, **kwargs) -> Any:
        """
        Call the tool with the given arguments asynchronously.
        This method should only be used for asynchronous tools.
        """
        if not self.callable:
            return None

        arguments = self._prepare_arguments(caller, **kwargs)

        # Check if the callable is a coroutine function
        if inspect.iscoroutinefunction(self.callable):
            result = await self.callable(**arguments)
        else:
            result = self.callable(**arguments)

        return result

    def _prepare_arguments(self, caller: Any, **kwargs) -> dict:
        """
        Prepare the arguments for the tool call.

        Args:
            caller (Any): The caller of the tool.
            **kwargs: Additional arguments to pass to the tool.

        Returns:
            dict: The prepared arguments.
        """
        arguments = {"self": caller, **kwargs}
        spec = inspect.getfullargspec(self.callable)
        annotations = spec.annotations
        for arg_name in spec.args:
            if arg_name not in arguments:
                if spec.defaults and arg_name in spec.args[-len(spec.defaults) :]:
                    default_index = spec.args[::-1].index(arg_name)
                    arguments[arg_name] = spec.defaults[-1 - default_index]

        for name, arg in arguments.items():
            if isinstance(arg, dict) and name in annotations:
                arguments[name] = annotations[name](**arg)

        return arguments

    @staticmethod
    def from_file(filepath: str) -> Tool | None:
        """
        Load a single Tool from a given file.
        """
        # valid .py file
        if (
            not os.path.isfile(filepath)
            or not filepath.endswith(".py")
            or os.path.basename(filepath).startswith("__")
        ):
            return None

        # Extract the module name from file name
        module_name = os.path.splitext(os.path.basename(filepath))[0]
        # Import the module dynamically
        spec = importlib.util.spec_from_file_location(module_name, filepath)
        if not spec or not spec.loader:
            logger.error(f"Cannot load module from {filepath}")
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # We expect a function that matches the module name
        function = getattr(module, module_name, None)
        if not inspect.isfunction(function):
            logger.warning(f"No function named '{module_name}' found in {filepath}.")
            return None

        return Tool(module_name, description=function.__doc__ or "", callable=function)

    @staticmethod
    def load(
        filepath: str | None = None,
        file_name: str | list[str] | None = None,
    ) -> list[Tool]:
        """
        Loads Python tool(s) from:
          1. A single .py file
          2. A directory of .py files
          3. A directory + specific file(s) (by name, without .py)

        If no filepath is given, we default to the current directory of this __init__.py.

        Args:
            filepath (str | None):
                - If None, defaults to directory of this __init__.py.
                - If it's a directory, we look for either `file_name` or all .py files.
                - If it's a path to a file, we load that single file.
            file_name (str | List[str] | None):
                - If None, load all .py files in the directory (excluding __*).
                - If a string, loads one specific file name (adds .py if missing).
                - If a list of strings, loads multiple file names (each gets .py if missing).

        Returns:
            list[Tool]: List of loaded Tool objects.
        """
        if not filepath:
            # Default to the directory containing this file
            filepath = os.path.dirname(__file__)

        found_tools = []
        # -----------------------------------------------------
        # CASE A: `filepath` is a direct *.py file -> load it
        # -----------------------------------------------------
        if os.path.isfile(filepath):
            # Make sure it is actually a .py file
            if filepath.endswith(".py") and not os.path.basename(filepath).startswith(
                "__"
            ):
                tool = Tool.from_file(filepath)
                if tool:
                    found_tools.append(tool)
                else:
                    logger.error(f"Cannot load tool from {filepath}")

        # -----------------------------------------------------
        # CASE B: `filepath` is a directory
        # -----------------------------------------------------
        elif os.path.isdir(filepath):
            # Normalize `file_name` into a list and load all .py files (except __*.py)
            files_to_process = (
                os.listdir(filepath)
                if file_name is None
                else [
                    f if f.endswith(".py") else f + ".py"
                    for f in ([file_name] if isinstance(file_name, str) else file_name)
                ]
            )

            # Process each file
            for f in files_to_process:
                if f.endswith(".py") and not f.startswith("__"):
                    full_path = os.path.join(filepath, f)
                    tool = Tool.from_file(full_path)
                    if tool:
                        found_tools.append(tool)
                    else:
                        logger.error(f"Cannot load tool from {full_path}")

        return found_tools

    def to_dict(self) -> dict[str, Any]:
        schema = self.schema or {}
        return {
            "type": "object",
            "description": self.description or self.name,
            "properties": {
                "intention": {
                    "type": "string",
                    "description": "Your reason for using this specific tool, and intended outcome.",
                    "minLength": 10,
                },
                "name": {"const": self.name},
                "arguments": schema.get("parameters", schema),
            },
            "required": ["intention", "name", "arguments"],
        }

    def __getattribute__(self, name: str) -> Any:
        try:
            return object.__getattribute__(self, name)
        except AttributeError:
            schema = object.__getattribute__(self, "schema")
            if name in schema:
                return schema[name]
            return None

    def __str__(self) -> str:
        tool = self.to_dict().get("properties", {})
        tool_str = f'\nTool name: "{self.name}"'
        tool_str += f'\nTool description:\n{self.description}'
        tool_str += f'\nTool schema:\n{json.dumps(tool, indent=2)}'
        return tool_str

    @staticmethod
    def from_mcp_tool(mcp_tool: MCPTool, server_id: str) -> Tool:
        """
        Convert an tool from the MCP protocol to a local Tool object.
        """
        schema = mcp_tool.inputSchema
        return Tool(mcp_tool.name, mcp_tool.description or "", schema=schema, mcp_server=server_id)


class ToolCall(BaseModel):
    """
    A tool call is an invocation of a tool.
    """

    intention: str
    """The reason or goal of the tool call. Minimum 10 characters."""
    name: str
    """The name of the tool to call."""
    arguments: dict[str, Any] | None = None
    """The arguments to pass to the tool."""

    def __str__(self) -> str:
        return self.model_dump_json(indent=2)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
