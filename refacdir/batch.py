from enum import Enum
from glob import glob
import re
import sys
import yaml

from refacdir.batch_renamer import BatchRenamer, Location
import custom_file_name_search_funcs


class StringFunction(Enum):
    REP = "rep"
    DIGITS = "digits"
    HEX = "hex"
    ALNUM = "alnum"

    def __call__(self, *args):
        if self == StringFunction.REP:
            return self.rep(*args)
        elif self == StringFunction.DIGITS:
            return self.digits(*args)
        elif self == StringFunction.HEX:
            return self.hex(*args)
        elif self == StringFunction.ALNUM:
            return self.alnum(*args)

    @staticmethod
    def rep(s="", n=1):
        return s * n

    @staticmethod
    def digits(n=1):
        return "[0-9]" * n

    @staticmethod
    def hex(n=1, lower=False, extra_chars=""):
        chars = "0-9a-f" if lower else "0-9A-F"
        return f"[{chars}{extra_chars}]" * n

    @staticmethod
    def alnum(n=1, lower=False, extra_chars=""):
        if lower == True:
            chars = "0-9a-z"
        elif lower == False:
            chars = "0-9A-Z"
        elif lower is None:
            chars = "0-9A-Za-z"
        return f"[{chars}{extra_chars}]" * n


class StringFunctionCall:
    def __init__(self, name, _function, *args):
        self.name = name
        self._function = _function
        self._args = args[0]
    
    def __call__(self):
        return self._function(*self._args)

    def __str__(self):
        return f"{self.name}({', '.join(map(str, self._args))})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, StringFunctionCall) and \
               other._function == self._function and \
               other._args == self._args

    def __hash__(self) -> int:
        return hash(str(self))


class FilenameMappingDefinition:
    NAMED_FUNCTIONS = {}
    GENERATED_PATTERNS = {}

    def __init__(self, pattern, function_calls=[]):
        if not pattern or pattern == "":
            raise Exception("Pattern not provided to FilenameMappingDefinition")
        self.pattern = pattern
        self.function_calls = function_calls

    def compile(self):
        if "{{" in self.pattern:
            temp = str(self.pattern)
            while "{{" in temp:
                count = 0
                for group in re.findall("{{(.*?)}}", temp):
                    if isinstance(group, tuple):
                        group = group[0]
                    subpattern = self.generate_subpattern(group, count)
                    if callable(subpattern):
                        return subpattern # This should be a function to search for files with more complex logic
                        # TODO replace this with some string identifier in the pattern to avoid regex in this case
                    else:
                        temp = temp.replace(f"{{{{{group}}}}}", subpattern)
                    count += 1
            return temp
        else:
            if len(self.function_calls) > 0:
                print(f"Warning - Functions defined for {self.pattern} but placement not defined.")
            return self.pattern

    def generate_subpattern(self, func_name="", index=0):
        if func_name in FilenameMappingDefinition.NAMED_FUNCTIONS:
            function_call = FilenameMappingDefinition.NAMED_FUNCTIONS[func_name]
        elif len(self.function_calls) > int(index):
            function_call = self.function_calls[int(index)]
        else:
            if not func_name or func_name.strip() == "":
                raise Exception("Not enough arguments provided to generate subpattern")
            try:
                # If the function is not defined in the config then it may be in custom file name search functions.
                return getattr(custom_file_name_search_funcs, func_name)
            except Exception as e:
                raise Exception(f"Function {func_name} not found in config filename_mapping_functions or in custom_file_name_search_funcs.py: {e}")
        return FilenameMappingDefinition.call_from_cache(function_call)

    @staticmethod
    def call_from_cache(function_call):
        if function_call in FilenameMappingDefinition.GENERATED_PATTERNS:
            return FilenameMappingDefinition.GENERATED_PATTERNS[function_call]
        else:
            res = function_call()
            FilenameMappingDefinition.GENERATED_PATTERNS[function_call] = res
            return res

    @staticmethod
    def add_named_function(function_call):
        FilenameMappingDefinition.NAMED_FUNCTIONS[function_call.name] = function_call

    @staticmethod
    def add_named_functions(funcs_list):
        for func in funcs_list:
            function_call = StringFunctionCall(
                func["name"],
                StringFunction[func["type"]],
                func["args"],
            )
            FilenameMappingDefinition.add_named_function(function_call=function_call)

    @staticmethod
    def compiled(pattern, funcs=[]):
        definition = FilenameMappingDefinition(pattern, funcs)
        return definition.compile()


def construct_mappings(mappings_list):
    mappings = {}
    for mapping in mappings_list:
        search_pattern = mapping["search_patterns"]
        funcs = mapping["funcs"] if "funcs" in mapping else []
        rename_tag = mapping["rename_tag"]
        if isinstance(search_pattern, str):
            mappings[FilenameMappingDefinition.compiled(search_pattern, funcs)] = rename_tag
        elif isinstance(search_pattern, list):
            for pattern in mapping["search_patterns"]:
                mappings[FilenameMappingDefinition.compiled(pattern, funcs)] = rename_tag
        else:
            raise Exception(f"Invalid search pattern type {type(search_pattern)}")
    return mappings

def construct_batch_renamer(yaml_dict={}, test=True, skip_confirm=False):
    name = yaml_dict["name"]
    mappings = construct_mappings(yaml_dict["mappings"])
    locations = [Location.construct(location) for location in yaml_dict["locations"]]
    renamer_function = yaml_dict["function"]
    test = yaml_dict["test"] if "test" in yaml_dict else test
    skip_confirm = yaml_dict["skip_confirm"] if "skip_confirm" in yaml_dict else skip_confirm
    renamer = BatchRenamer(name, mappings, locations, test=test, skip_confirm=skip_confirm)
    return renamer, renamer_function

def main(test=True, skip_confirm=False):
    configurations = glob("configs\\*.yaml", recursive=False)
    failed_count = 0
    count = 0
    failures = []

    if "config_example.yaml" in configurations:
        configurations.remove("config_example.yaml")

    for config in configurations:
        print(f"Running renames for {config}")
        with open(config,'r') as f:
            try:
                config_wrapper = yaml.load(f, Loader=yaml.FullLoader)
            except yaml.YAMLError as e:
                failed_count += 1
                print(f"Error loading {config}: {e}")
                failures.append(f"Config {config} failed to load: {e}")
                continue
            FilenameMappingDefinition.add_named_functions(config_wrapper["filename_mapping_functions"])
            renamer_count = -1
            for _renamer in config_wrapper["renamers"]:
                renamer_count += 1
                try:
                    renamer, renamer_function = construct_batch_renamer(_renamer, test=test, skip_confirm=skip_confirm)
                except KeyError as e:
                    failed_count += 1
                    if "name" in _renamer:
                        name = _renamer["name"]
                        error = f"Error in {config} renamer {name}:  {e}"
                    else:
                        error = f"Error in {config} renamer {renamer_count}:  {e}"
                    failures.append(error)
                    print(error)
                    continue
                try:
                    renamer.execute(renamer_function)
                    count += 1
                except Exception as e:
                    failed_count += 1
                    if "name" in _renamer:
                        name = _renamer["name"]
                        error = f"{config} renamer {name} failed:  {e}"
                    else:
                        error = f"{config} renamer {renamer_count} failed:  {e}"
                    failures.append(error)
                    print(error)                        

    print(f"{count} renames completed")
    if failed_count > 0:
        print(f"{failed_count} renames failed")
        for failure in failures:
            print(failure)
    else:
        print("All renames completed successfully")


if __name__ == "__main__":
    test = False # TODO update to False
    skip_confirm = False
    if len(sys.argv) > 1:
        if "test".startswith(sys.argv[1].lower()):
            test = True
        if "skip_confirm".startswith(sys.argv[1].lower()):
            skip_confirm = True
    main(test=test, skip_confirm=skip_confirm)
