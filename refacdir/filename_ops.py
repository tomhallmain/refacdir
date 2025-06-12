from enum import Enum
import re
from refacdir.utils.logger import setup_logger

import custom_file_name_search_funcs

# Set up logger for filename operations
logger = setup_logger('filename_ops')

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
                logger.warning(f"Functions defined for {self.pattern} but placement not defined.")
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
        if type(funcs_list) == list:
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

    @staticmethod
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

class FiletypesDefinition:
    NAMED_DEFINITIONS = {}

    def __init__(self, name, extensions_list=[]):
        self.name = name
        self._filetypes = []

        for extension in extensions_list:
            if not isinstance(extension, str):
                raise Exception(f"Invalid filetype definition, expected type string, got: {type(extension)}")
            extension = extension.strip()
            if len(extension) == 0 or extension[0]!= ".":
                raise Exception(f"Invalid filetype definition, expected a valid extension, got {extension}")
            self._filetypes.append(extension)

    @staticmethod
    def add_named_definition(definition):
        FiletypesDefinition.NAMED_DEFINITIONS[definition.name] = definition

    @staticmethod
    def add_named_definitions(definitions_list):
        if type(definitions_list) == list:
            for defn in definitions_list:
                definition = FiletypesDefinition(
                    defn["name"],
                    extensions_list=defn["extensions"],
                )
                FiletypesDefinition.add_named_definition(definition=definition)

    @staticmethod
    def compile(name_string):
        if "{{" in name_string:
            for group in re.findall("{{(.*?)}}", name_string):
                if isinstance(group, tuple):
                    group = group[0]
                return FiletypesDefinition.NAMED_DEFINITIONS[group]
            raise KeyError(name_string)
        else:
            return FiletypesDefinition.NAMED_DEFINITIONS[name_string]

    @staticmethod
    def get_definitions(definitions_obj):
        if isinstance(definitions_obj, list):
            return FiletypesDefinition(str(definitions_obj), extensions_list=definitions_obj)._filetypes
        elif isinstance(definitions_obj, str):
            try:
                return FiletypesDefinition.compile(definitions_obj)._filetypes
            except KeyError as e:
                raise Exception(f"Invalid filetypes definition name: {e}")
        else:
            raise Exception(f"Invalid filetype definition type: {type(definitions_obj)} ({definitions_obj})")
