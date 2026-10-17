#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""R38 selected tool execution and metadata-discovery closure regressions."""

from __future__ import annotations

import hashlib
import importlib.machinery
import json
import os
import shlex
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "tools/evidence-v4/evidence-v4-toolchain.ts"
PROGRAM = (
    "const input=await Bun.stdin.json();const moduleURL=input.module??"
    + json.dumps(MODULE.as_uri())
    + ";const {discoverPythonAdapter,discoverNodeAdapter,discoverNativeAdapter,createToolchainSession}=await import(moduleURL);"
    + "const {hashToolRoots,parseMachOLoadCommands,isRustupProxy}=await import(new URL('evidence-v4-toolchain-common.ts',moduleURL).href);"
    + "const {D,H}=await import(new URL('evidence-v4-model.ts',moduleURL).href);\n"
    + r"""
let session={async run(request){
  const child=Bun.spawn(request.command,{cwd:request.cwd,env:request.environment,stdout:'pipe',stderr:'pipe'});
  const [stdout,stderr,code]=await Promise.all([new Response(child.stdout).arrayBuffer(),new Response(child.stderr).arrayBuffer(),child.exited]);
  return {stdout:Buffer.from(stdout),stderr:Buffer.from(stderr),error:null,
    termination:{exit_code:code,signal:null,timed_out:false,cancelled:false}};
}};
const resolveCommand=async(command,cwd=input.root,environment=input.env)=>{
  const candidates=command.includes('/')?[path.resolve(cwd,command)]:(environment.PATH??'').split(path.delimiter).map(directory=>path.resolve(cwd,directory,command));
  for(const invoked of candidates){try{await fs.access(invoked,fs.constants.X_OK);const realpath=await fs.realpath(invoked);if((await fs.stat(realpath)).isFile())return {invoked,realpath};}
    catch(error){if(!['ENOENT','ENOTDIR','EACCES'].includes(error.code))throw error;}}
  throw Error('Executable not found: '+command);
};
const fs=await import('node:fs/promises'),path=await import('node:path');
if(input.real_native){
  const {createNativeSession}=await import(new URL('evidence-v4-native.ts',input.module).href);
  session=await createNativeSession({cwd:input.root,runId:crypto.randomUUID()});
}
const declaration=input.declaration??{id:'python',kind:'tree',locator:{mode:'adapter',value:'python-runtime',cwd:'.',subject:[input.python]},requires:[],version_command:null,version_cwd:null,accept:{sha256:[],version_contains:[]}};
const context={root:input.root,cwd:input.root,cwdRelative:'.',subject:declaration.locator.subject,effectiveEnv:input.env,declaration,
  session,applicationContexts:[],commandContexts:input.commands??[],resolveCommand,
  async probe(command,settings={}){
    const cwd=settings.cwd??input.root,result=await session.run({command,cwd,environment:settings.env??input.env});
    if(result.termination.exit_code!==0)throw Error('Probe failed: '+result.stderr.toString());
    return {...result,code:result.termination.exit_code,identity:{command:[...command],cwd:path.relative(input.root,cwd)||'.',stdout_hash:H(result.stdout),stderr_hash:H(result.stderr),exit_code:result.termination.exit_code}};
  },
  native(subject,settings){return discoverNativeAdapter(context,subject,settings);}
};
try{
  if(input.op==='macho'){
    process.stdout.write(JSON.stringify({ok:true,result:parseMachOLoadCommands(input.text)}));
  }else if(input.op==='rustup-proxy'){
    process.stdout.write(JSON.stringify({ok:true,proxy:await isRustupProxy(await resolveCommand(input.command))}));
  }else if(input.op==='bound'){
    const tools=createToolchainSession({root:input.root,env:input.env,policy:input.policy,session});
    await tools.assertCommandBound(input.command,input.root,input.ids);
    process.stdout.write(JSON.stringify({ok:true}));
  }else if(input.op==='resolve'){
    const tools=createToolchainSession({root:input.root,env:input.env,policy:{toolchains:[]},session});
    const selected=await Promise.all(input.commands.map(command=>tools.resolveCommand(command)));
    process.stdout.write(JSON.stringify({ok:true,selected}));
  }else if(['capture','stability','optional-install'].includes(input.op)){
    const tools=createToolchainSession({root:input.root,env:input.env,policy:input.policy,session});
    const identities=await tools.capture(input.ids??[]);
    if(input.op==='optional-install'){
      if(input.append)await fs.appendFile(input.install_file,'\0');else await fs.writeFile(input.install_file,'VALUE = 2\n');
      try{
        await tools.revalidate(input.ids??[]);
        process.stdout.write(JSON.stringify({ok:true,accepted:true}));
      }catch(error){process.stdout.write(JSON.stringify({ok:true,accepted:false,error:error instanceof Error?error.message:String(error)}));}
    }else{
      let after=null;
      if(input.op==='stability')for(let index=0;index<(input.iterations??1);index++)after=await tools.revalidate(input.ids??[]);
      process.stdout.write(JSON.stringify({ok:true,identities,after}));
    }
  }else{
    const result=await (input.op==='node'?discoverNodeAdapter(context):input.op==='native'?discoverNativeAdapter(context):discoverPythonAdapter(context));
    const files=input.hash?await hashToolRoots(result.roots):[];
    process.stdout.write(JSON.stringify({ok:true,requirements:result.fileRequirements??[],sourceRequirements:result.sourceRequirements,discovery:result.discovery??[],roots:result.roots,files,digest:D('test-tool-files',files)}));
  }
}catch(error){process.stdout.write(JSON.stringify({ok:false,error:error instanceof Error?error.message:String(error)}));}
finally{if(input.real_native)await session.release();}
"""
)

SHIM = r"""#!/bin/sh
basedir=$(dirname "$(echo "$0" | sed -e 's,\\,/,g')")

case `uname` in
    *CYGWIN*|*MINGW*|*MSYS*)
        if command -v cygpath > /dev/null 2>&1; then
            basedir=`cygpath -w "$basedir"`
        fi
    ;;
esac

if [ -z "$NODE_PATH" ]; then
  export NODE_PATH="__PATH__"
else
  export NODE_PATH="__PATH__:$NODE_PATH"
fi
if [ -x "$basedir/node" ]; then
  exec "$basedir/node"  "$basedir/../tsx/dist/cli.mjs" "$@"
else
  exec node  "$basedir/../tsx/dist/cli.mjs" "$@"
fi
"""


def invoke(request: dict) -> dict:
    process = subprocess.run(
        [shutil.which("bun"), "--eval", PROGRAM],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=240,
    )
    if process.returncode:
        raise AssertionError(process.stdout + process.stderr)
    return json.loads(process.stdout)


def declaration(identifier, adapter, subject, requires=()):
    return {
        "id": identifier,
        "kind": "tree",
        "locator": {
            "mode": "adapter",
            "value": adapter,
            "cwd": ".",
            "subject": subject,
        },
        "requires": list(requires),
        "version_command": None,
        "version_cwd": None,
        "accept": {"sha256": [], "version_contains": []},
    }


LOADER_SOURCE = """import importlib.util, sys
from pathlib import Path
def _input(root, relative):
 path = root / relative
 if path.is_symlink() or path.resolve() != path or not path.is_file():
  raise ValueError('missing or redirected input')
 return path
def _module(root, relative, name):
 path = _input(root, relative)
 spec = importlib.util.spec_from_file_location(name, path)
 if spec is None or spec.loader is None:
  raise ValueError('cannot load collector')
 module = importlib.util.module_from_spec(spec)
 sys.modules[name] = module
 spec.loader.exec_module(module)
 return module
"""

REVIEWED_HOMEBREW_HOOK = "# This file is created by Homebrew and is executed on each python startup.\n# Don't print from here, or else python command line scripts may fail!\n# <https://docs.brew.sh/Homebrew-and-Python>\nimport re\nimport os\nimport site\nimport sys\nif sys.version_info[:2] != (3, 14):\n    # This can only happen if the user has set the PYTHONPATH to a mismatching site-packages directory.\n    # Every Python looks at the PYTHONPATH variable and we can't fix it here in sitecustomize.py,\n    # because the PYTHONPATH is evaluated after the sitecustomize.py. Many modules (e.g. PyQt4) are\n    # built only for a specific version of Python and will fail with cryptic error messages.\n    # In the end this means: Don't set the PYTHONPATH permanently if you use different Python versions.\n    exit(f'Your PYTHONPATH points to a site-packages dir for Python 3.14 '\n         f'but you are running Python {sys.version_info[0]}.{sys.version_info[1]}!\\n'\n         f'     PYTHONPATH is currently: \"{os.environ[\"PYTHONPATH\"]}\"\\n'\n         f'     You should `unset PYTHONPATH` to fix this.')\n# Only do this for a brewed python:\nif os.path.realpath(sys.executable).startswith('/opt/homebrew/Cellar/python@3.14'):\n    # the Cellar site-packages is a symlink to the HOMEBREW_PREFIX\n    # site_packages; prefer the shorter paths\n    long_prefix = re.compile(r'/opt/homebrew/Cellar/python@3.14/[0-9\\._abrc]+/(?:Frameworks/Python\\.framework/Versions/3.14/)?lib/python3.14/site-packages')\n    sys.path = [long_prefix.sub('/opt/homebrew/lib/python3.14/site-packages', p) for p in sys.path]\n    # Set the sys.executable to use the opt_prefix. Only do this if PYTHONEXECUTABLE is not\n    # explicitly set and we are not in a virtualenv:\n    if 'PYTHONEXECUTABLE' not in os.environ and sys.prefix == sys.base_prefix:\n        sys.executable = sys._base_executable = '/opt/homebrew/opt/python@3.14/bin/python3.14'\nif 'PYTHONHOME' not in os.environ:\n    cellar_prefix = re.compile(r'/opt/homebrew/Cellar/python@3.14/[0-9\\._abrc]+(?=/|$)')\n    if os.path.realpath(sys.base_prefix).startswith('/opt/homebrew/Cellar/python@3.14'):\n        new_prefix = cellar_prefix.sub('/opt/homebrew/opt/python@3.14', sys.base_prefix)\n        site.PREFIXES[:] = [new_prefix if x == sys.base_prefix else x for x in site.PREFIXES]\n        if sys.prefix == sys.base_prefix:\n            sys.prefix = new_prefix\n        sys.base_prefix = new_prefix\n    if os.path.realpath(sys.base_exec_prefix).startswith('/opt/homebrew/Cellar/python@3.14'):\n        new_exec_prefix = cellar_prefix.sub('/opt/homebrew/opt/python@3.14', sys.base_exec_prefix)\n        site.PREFIXES[:] = [new_exec_prefix if x == sys.base_exec_prefix else x for x in site.PREFIXES]\n        if sys.exec_prefix == sys.base_exec_prefix:\n            sys.exec_prefix = new_exec_prefix\n        sys.base_exec_prefix = new_exec_prefix\n# Make site.getsitepackages() return the HOMEBREW_PREFIX site-packages,\n# but only if we are outside a venv or in one with include-system-site-packages.\nif sys.base_prefix in site.PREFIXES:\n    site.PREFIXES.insert(site.PREFIXES.index(sys.base_prefix), '/opt/homebrew')\n    site.addsitedir('/opt/homebrew/lib/python3.14/site-packages')\n# Check for and add the prefix of split Python formulae.\nfor split_module in [\"tk\", \"gdbm\"]:\n    split_prefix = f\"/opt/homebrew/opt/python-{split_module}@3.14/libexec\"\n    if os.path.isdir(split_prefix):\n        sys.path.append(split_prefix)\n"


class ToolchainReview(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fv-v4-toolchain-review-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "project"
        self.root.mkdir()
        self.external = self.base / "installed"
        self.external.mkdir()
        self.python = str(Path(sys.executable).resolve())
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}

    def write(self, file, content, executable=False):
        target = Path(file)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if executable:
            target.chmod(0o755)
        return target

    def python_request(self, source):
        script = self.write(self.root / "check.py", source)
        return {
            "op": "python",
            "root": str(self.root),
            "python": self.python,
            "env": {**self.env, "PYTHONPATH": str(self.external)},
            "commands": [
                {
                    "subject": [self.python, str(script)],
                    "cwd": str(self.root),
                    "toolchain": ["python"],
                }
            ],
        }

    def capture_python(self, source):
        request = self.python_request(source)
        request.update(
            op="capture",
            ids=["python"],
            policy={
                "toolchains": [declaration("python", "python-runtime", [self.python])],
                "recipes": [],
                "preflight": [],
                "claim_checker": {
                    "command": request["commands"][0]["subject"],
                    "cwd": ".",
                    "toolchain": ["python"],
                },
            },
        )
        return invoke(request)

    def test_guarded_absence_requires_one_direct_import(self):
        sources = (
            "import sys\ntry:\n if sys.version_info >= (3,11):\n  import tomllib\n else:\n  import absent_fv_module\n import external_plugin\nexcept ImportError:\n pass\n",
            "try:\n import absent_fv_module\n import external_plugin\nexcept ImportError:\n pass\n",
            "try:\n def load():\n  import absent_fv_module\n import external_plugin\nexcept ImportError:\n pass\n",
        )
        self.write(self.external / "external_plugin.py", "VALUE = 1\n")
        for source in sources:
            with self.subTest(source=source):
                result = invoke(self.python_request(source))
                self.assertFalse(result["ok"], result)

    def test_python_path_mutation_allowlist_refuses_other_forms(self):
        sources = (
            "sys.path += ['plugins']",
            "del sys.path[0]",
            "sys.path = ['plugins']",
            "sys.path.extend(['plugins'])",
            "sys.path.reverse()",
            "sys.path_hooks.append(None)",
            "sys.meta_path = []",
            "with open(__file__) as stream:\n sys.path.insert(0, 'plugins')",
            "for item in ['plugins']:\n sys.path.insert(0, item)",
            "while flag:\n sys.path.append('plugins')",
            "result = sys.path.append('plugins')",
            "change = sys.path.append\nchange('plugins')",
            "getattr(sys, 'path').append('plugins')",
            "saved = sys.path",
            "holder.path = sys.path",
            "holder = {'path': sys.path}\nholder['path'].append('plugins')",
            "def setup(paths=sys.path):\n paths.append('plugins')\nsetup()",
            "def setup(runtime):\n runtime.path.append('plugins')\nsetup(sys)",
            "for item in ['plugins']:\n import sys as runtime\n runtime.path.append(item)",
            "if condition:\n import sys as runtime\n runtime.path.append('plugins')",
            "def setup():\n import sys as runtime\n runtime.path.append('plugins')\nsetup()",
        )
        for source in sources:
            with self.subTest(source=source):
                result = invoke(self.python_request("import sys\n" + source + "\n"))
                self.assertFalse(result["ok"], result)
                self.assertIn("Python", result["error"])

    def test_python_dynamic_loader_allowlist_refuses_other_forms(self):
        sources = (
            "import site\nsite.addsitedir('plugins')",
            "import importlib\nimportlib.__import__('json')",
            "from importlib.machinery import SourceFileLoader\nSourceFileLoader('x','plugins/x.py').load_module()",
            "import importlib.util\nimportlib.util.find_spec('json')",
            "exec(compile('import external_plugin', '<test>', 'exec'))",
            "import runpy\ndef load(file):\n runpy.run_path(file)\nload(selected)",
            "import importlib\ndef load(callback):\n callback(selected)\nload(importlib.import_module)",
        )
        for source in sources:
            with self.subTest(source=source):
                result = invoke(self.python_request(source + "\n"))
                self.assertFalse(result["ok"], result)
                self.assertIn("Python", result["error"])

    def test_python_warning_and_extended_option_selectors_refuse(self):
        for options in (
            ["-W", "ignore::external_plugin.Warning"],
            ["-Wignore::external_plugin.Warning"],
            ["-X", "presite=external_plugin"],
        ):
            with self.subTest(options=options):
                request = self.python_request("VALUE = 1\n")
                request["commands"][0]["subject"][1:1] = options
                result = invoke(request)
                self.assertFalse(result["ok"], result)
                self.assertIn("Python interpreter selection", result["error"])
        request = self.python_request("VALUE = 1\n")
        request["env"]["PYTHONWARNINGS"] = "ignore::external_plugin.Warning"
        result = invoke(request)
        self.assertFalse(result["ok"], result)
        self.assertIn("PYTHONWARNINGS", result["error"])

    def test_python_literal_helper_loader_binds_target_imports(self):
        self.write(self.root / "loaded.py", "import external_plugin\n")
        module = self.write(self.external / "external_plugin.py", "VALUE = 1\n")
        source = (
            LOADER_SOURCE
            + """def check(root):
 return _module(root, 'loaded.py', 'loaded')
"""
        )
        result = invoke(self.python_request(source))
        self.assertTrue(result["ok"], result)
        self.assertIn(
            str(module),
            {
                file
                for requirement in result["requirements"]
                for file in requirement["files"]
            },
        )
        rejected = self.capture_python(source)
        self.assertFalse(rejected["ok"], rejected)
        self.assertIn("external_plugin.py", rejected["error"])
        rejected = invoke(
            self.python_request(
                source.replace("'loaded.py', 'loaded'", "selected, 'loaded'")
            )
        )
        self.assertFalse(rejected["ok"], rejected)
        self.assertIn("non-literal Python loader", rejected["error"])

    def test_ca19_non_source_entries_and_loader_targets_refuse(self):
        for name in ("gate", "app.pyz", "app.pyc"):
            script = self.write(self.root / name, "import external_plugin\n")
            request = self.python_request("VALUE = 1\n")
            request["commands"][0]["subject"][1] = str(script)
            result = invoke(request)
            self.assertFalse(result["ok"], result)
            self.assertIn("Python source entry", result["error"])
        directory = self.root / "directory.py"
        directory.mkdir()
        self.write(directory / "__main__.py", "import external_plugin\n")
        request["commands"][0]["subject"][1] = str(directory)
        self.assertFalse(invoke(request)["ok"])
        for target in ("gate", "app.pyz", "app.pyc"):
            result = invoke(
                self.python_request(
                    "import runpy\nrunpy.run_path(" + repr(target) + ")\n"
                )
            )
            self.assertFalse(result["ok"], result)
            self.assertIn("Python source loader target", result["error"])

    def test_ca20_opaque_modules_and_stdlib_import_by_name_refuse(self):
        for source in (
            "import sys\nsys.modules['importlib'].import_module('external_plugin')",
            "import sys\nloader = sys.modules.get('importlib')\nloader.import_module('external_plugin')",
            "import sys\nsys.modules.pop('importlib')('external_plugin')",
            "import sys\ngetattr(sys.modules['importlib'], 'import_module')('external_plugin')",
            "import logging.config\nlogging.config.dictConfig({'version': 1})",
            "from logging import config\nconfig.dictConfig({'version': 1})",
            "import logging\nlogging.config.dictConfig({'version': 1})",
            "import pickle\npickle.loads(payload)",
            "import shelve\nshelve.open('data')",
            "import pydoc\npydoc.locate('external_plugin.Handler')",
        ):
            with self.subTest(source=source):
                result = invoke(self.python_request(source + "\n"))
                self.assertFalse(result["ok"], result)
                self.assertIn("Python", result["error"])
        result = invoke(
            self.python_request(
                "import sys\nprevious = sys.modules.get('fixture')\n"
                "sys.modules.pop('fixture', None)\n"
                "sys.modules['fixture'] = previous\n"
                "sys.modules['alias'] = sys.modules[__name__]\n"
            )
        )
        self.assertTrue(result["ok"], result)

    def test_ca03_opaque_module_container_default_and_escape_paths_refuse(self):
        for statement in (
            "holder = {'loader': sys.modules['importlib']}\nholder['loader'].import_module('external_plugin')",
            "holder = {'registry': sys.modules}",
            "holder = {'lookup': sys.modules.get}",
            "holder = [sys.modules['importlib']]",
            "holder = (sys.modules.get,)",
            "holder = {sys.modules['importlib']}",
            "holder = [loader for loader in sys.modules]",
            "def load(loader=sys.modules['importlib']):\n loader.import_module('external_plugin')",
            "def load(*, loader=sys.modules.get):\n pass",
            "load = lambda loader=sys.modules['importlib']: loader",
            "holder = {}\nholder['loader'] = sys.modules['importlib']",
            "holder.loader = sys.modules['importlib']",
            "class Holder:\n loader = sys.modules['importlib']",
            "loader = sys.modules['importlib']\nclass Holder:\n loader = loader\nHolder.loader.import_module('external_plugin')",
            "registry = sys.modules\nclass Holder:\n registry = registry\nHolder.registry['importlib'].import_module('external_plugin')",
            "saved = {name: sys.modules.get(name) for name in ('importlib',)}\nclass Holder:\n saved = saved\nHolder.saved['importlib'].import_module('external_plugin')",
            "loader = sys.modules['importlib']\nclass Holder:\n if condition:\n  loader = loader\nHolder.loader.import_module('external_plugin')",
            "class Holder:\n loader = importlib\nHolder.loader.import_module('external_plugin')",
            "loader = sys.modules['importlib']\nclass Holder:\n loader = 1\n def find(self):\n  return loader\nHolder().find().import_module('external_plugin')",
            "loader = sys.modules['importlib']\nclass Holder:\n loader = 1\n class Nested:\n  loader = loader\nHolder.Nested.loader.import_module('external_plugin')",
            "loader = sys.modules['importlib']\nclass Holder:\n loader = 1\n find = lambda: loader\nHolder.find().import_module('external_plugin')",
            "def load():\n return sys.modules['importlib']",
            "holder = sys.modules['importlib'] or missing",
            "if condition:\n loader = sys.modules['importlib']\nloader.import_module('external_plugin')",
            "for item in [1]:\n loader = sys.modules['importlib']\nloader.import_module('external_plugin')",
            "try:\n loader = sys.modules['importlib']\nexcept Exception:\n pass\nloader.import_module('external_plugin')",
        ):
            with self.subTest(statement=statement):
                result = invoke(
                    self.python_request("import importlib, sys\n" + statement + "\n")
                )
                self.assertFalse(result["ok"], result)
                self.assertIn("Python", result["error"])
        result = invoke(
            self.python_request(
                "import sys\nprevious = sys.modules.get('fixture')\n"
                "if previous is None:\n sys.modules.pop('fixture', None)\n"
                "else:\n sys.modules['fixture'] = previous\n"
                "registry = sys.modules\nlookup = registry.get\n"
                "previous = lookup('fixture', previous)\n"
                "registry['fixture'] = previous\n"
                "class Ordinary:\n value = 1\n def result(self):\n  return 1\n"
                " def previous(self):\n  return 1\n identity = lambda previous: previous\n"
            )
        )
        self.assertTrue(result["ok"], result)

    def test_ca03_unmodeled_class_comprehensions_refuse(self):
        for comprehension in (
            "[loader for item in (1,)]",
            "{item: loader for item in (1,)}",
            "{loader for item in (1,)}",
            "(loader for item in (1,))",
        ):
            with self.subTest(comprehension=comprehension):
                result = invoke(
                    self.python_request(
                        "import sys\nloader = sys.modules['importlib']\n"
                        "class Holder:\n loader = 1\n saved = " + comprehension + "\n"
                    )
                )
                self.assertFalse(result["ok"], result)
                self.assertIn("Python", result["error"])
        ordinary = invoke(
            self.python_request(
                "values = [value for value in (1, 2)]\n"
                "class Ordinary:\n def values(self):\n"
                "  return [value for value in (1, 2)]\n"
            )
        )
        self.assertTrue(ordinary["ok"], ordinary)

    def test_ca08_known_selectors_survive_branch_joins(self):
        for branch in (
            "if bool(1):\n loader = importlib",
            "for item in (1,):\n loader = importlib",
            "try:\n loader = importlib\nexcept Exception:\n pass",
        ):
            for class_scope in (False, True):
                with self.subTest(branch=branch, class_scope=class_scope):
                    source = "import importlib\n"
                    if class_scope:
                        source += "class Holder:\n" + "\n".join(
                            " " + line for line in branch.splitlines()
                        )
                        source += "\nHolder.loader.import_module('external_plugin')\n"
                    else:
                        source += branch + "\nloader.import_module('external_plugin')\n"
                    result = invoke(self.python_request(source))
                    self.assertFalse(result["ok"], result)
                    self.assertIn("Python", result["error"])

    def test_ca09_unhandled_statement_forms_refuse(self):
        self.write(self.external / "external_plugin.py", "VALUE = 1\n")
        for source in (
            "match 1:\n case 1:\n  import external_plugin\n",
            "import importlib, sys\nloader = sys.modules['importlib']\n"
            "class Holder:\n loader = 1\n match 1:\n  case 1:\n"
            "   saved = [loader for item in (1,)]\n",
            "try:\n raise ExceptionGroup('group', [ValueError()])\n"
            "except* ValueError:\n import external_plugin\n",
            "type Loader = object\n",
        ):
            with self.subTest(source=source):
                result = invoke(self.python_request(source))
                self.assertFalse(result["ok"], result)
        ordinary = invoke(
            self.python_request(
                "state = None\n"
                "def update():\n global state\n state = 1\n assert state == 1\n"
                "def outer():\n value = 0\n def inner():\n"
                "  nonlocal value\n  value = 1\n return inner\n"
                "for item in (1,):\n if item:\n  continue\n break\n"
                "try:\n raise ValueError('expected')\nexcept ValueError:\n pass\n"
            )
        )
        self.assertTrue(ordinary["ok"], ordinary)

    def test_ca03_literal_registry_snapshot_restore_retains_opaque_modules(self):
        self.write(self.root / "exercise.py", "VALUE = 1\n")
        source = """import runpy, sys
from pathlib import Path

def load_exercise():
    previous_path = sys.path[:]
    previous_modules = {name: sys.modules.get(name) for name in ('provider', 'wire')}
    try:
        for name in previous_modules:
            sys.modules.pop(name, None)
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        return runpy.run_path(str(Path(__file__).with_name('exercise.py')))
    finally:
        sys.path[:] = previous_path
        for name, module in previous_modules.items():
            sys.modules.pop(name, None)
            if module is not None:
                sys.modules[name] = module

load_exercise()
"""
        result = invoke(self.python_request(source))
        self.assertTrue(result["ok"], result)
        for selected_names in ("('alpha',)", "['first', 'second', 'third']"):
            with self.subTest(selected_names=selected_names):
                result = invoke(
                    self.python_request(
                        source.replace("('provider', 'wire')", selected_names)
                    )
                )
                self.assertTrue(result["ok"], result)
        for escaped in (
            ("import importlib\n" + source)
            .replace("('provider', 'wire')", "('importlib', 'wire')")
            .replace(
                "    try:\n",
                "    previous_modules['importlib'].import_module('external_plugin')\n"
                "    try:\n",
                1,
            ),
            source.replace(
                "sys.modules[name] = module",
                "module.import_module('external_plugin')",
            ),
            source.replace(
                "    try:\n", "    holder = [previous_modules]\n    try:\n", 1
            ),
            source.replace(
                "    try:\n",
                "    def load(saved=previous_modules):\n        pass\n    try:\n",
                1,
            ),
        ):
            with self.subTest(escaped=escaped):
                result = invoke(self.python_request(escaped))
                self.assertFalse(result["ok"], result)
                self.assertIn("Python", result["error"])

    def test_ca21_split_formula_stdlib_imports_refuse(self):
        for module in ("tkinter", "tkinter.ttk", "dbm", "dbm.gnu"):
            with self.subTest(module=module):
                result = invoke(self.python_request("import " + module + "\n"))
                self.assertFalse(result["ok"], result)
                self.assertIn("split-formula", result["error"])

    def test_ca21_transitive_stdlib_inventory_binds_external_parts_without_loading(
        self,
    ):
        split = self.write(
            self.external / "_tkinter.py",
            "raise AssertionError('stdlib discovery must not execute this module')\n",
        )
        for source in ("import _tkinter\n", "import turtle\n"):
            with self.subTest(source=source):
                result = invoke(self.python_request(source))
                self.assertTrue(result["ok"], result)
                self.assertIn(
                    str(split),
                    {
                        file
                        for requirement in result["requirements"]
                        for file in requirement["files"]
                    },
                )
        undeclared = self.capture_python("import turtle\n")
        self.assertFalse(undeclared["ok"], undeclared)
        self.assertIn("explicit installed tool declaration", undeclared["error"])
        self.assertIn("_tkinter.py", undeclared["error"])
        request = self.python_request("import turtle\n")
        runtime = declaration(
            "python", "python-runtime", [self.python], requires=["split"]
        )
        request.update(
            op="capture",
            ids=["python"],
            policy={
                "toolchains": [
                    runtime,
                    {
                        "id": "split",
                        "kind": "file",
                        "locator": {"mode": "path", "value": str(split)},
                        "requires": [],
                        "version_command": None,
                        "version_cwd": None,
                        "accept": {"sha256": [], "version_contains": []},
                    },
                ],
                "recipes": [],
                "preflight": [],
                "claim_checker": {
                    "command": request["commands"][0]["subject"],
                    "cwd": ".",
                    "toolchain": ["python"],
                },
            },
        )
        declared = invoke(request)
        self.assertTrue(declared["ok"], declared)

    def test_ca21_transitive_external_stdlib_packages_refuse(self):
        self.write(self.external / "tkinter/__init__.py", "VALUE = 1\n")
        result = invoke(self.python_request("import turtle\n"))
        self.assertFalse(result["ok"], result)
        self.assertIn("stdlib package outside runtime roots: tkinter", result["error"])

    def test_ca21_absent_stdlib_availability_is_revalidated(self):
        self.assertNotEqual(sys.platform, "win32")
        request = self.python_request("import argparse, json, pathlib\n")
        request.update(
            op="optional-install",
            ids=["python"],
            install_file=str(self.external / "winreg.py"),
            policy={
                "toolchains": [declaration("python", "python-runtime", [self.python])],
                "recipes": [],
                "preflight": [],
                "claim_checker": {
                    "command": request["commands"][0]["subject"],
                    "cwd": ".",
                    "toolchain": ["python"],
                },
            },
        )
        result = invoke(request)
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["accepted"], result)
        self.assertIn("changed: python", result["error"])

    def test_ca21_project_stdlib_shadows_require_sources_and_path_history(self):
        shadow = self.write(self.root / "plugins/string.py", "import external_plugin\n")
        plugin = self.write(self.external / "external_plugin.py", "VALUE = 1\n")
        result = invoke(
            self.python_request(
                "import sys\nfrom pathlib import Path\n"
                "previous = sys.path.copy()\n"
                "sys.path.insert(0, str(Path(__file__).parent / 'plugins'))\n"
                "VALUE = 1\n"
                "sys.path[:] = previous\n"
            )
        )
        self.assertTrue(result["ok"], result)
        self.assertIn(str(shadow), result["sourceRequirements"]["files"])
        required = {
            file
            for requirement in result["requirements"]
            for file in requirement["files"]
        }
        self.assertIn(str(plugin), required)
        self.assertNotIn(str(shadow), required)

    def test_ca21_ordinary_dossier_setup_and_builtin_precedence_preserved(self):
        shadow = self.write(
            self.root / "sys.py",
            "raise AssertionError('builtin precedence must ignore this file')\n",
        )
        self.write(self.external / "unselected_package/__init__.py", "import missing\n")
        request = self.python_request(
            "import argparse, hashlib, importlib.util, json, os, pathlib, re, subprocess, sys\n"
            "ROOT = pathlib.Path(__file__).resolve().parents[0]\n"
        )
        isolated = dict(request["commands"][0])
        isolated["subject"] = [self.python, "-I", "-B", isolated["subject"][-1]]
        request["commands"].append(isolated)
        result = invoke(request)
        self.assertTrue(result["ok"], result)
        self.assertNotIn(str(shadow), result["sourceRequirements"]["files"])
        self.assertFalse(
            any(
                "unselected_package" in file
                for requirement in result["requirements"]
                for file in requirement["files"]
            )
        )

    @unittest.skipUnless(
        sysconfig.get_config_var("PYTHONFRAMEWORK"),
        "selected interpreter is not a framework build",
    )
    def test_ca21_framework_runtime_library_is_content_bound(self):
        library = (
            Path(sysconfig.get_config_var("PYTHONFRAMEWORKPREFIX"))
            / sysconfig.get_config_var("LDLIBRARY")
        ).resolve()
        result = self.capture_python("import json\n")
        self.assertTrue(result["ok"], result)
        expected = "sha256:" + hashlib.sha256(library.read_bytes()).hexdigest()
        self.assertIn(
            expected,
            {
                entry.get("hash")
                for identity in result["identities"]
                for entry in identity["files"]
            },
        )

    @unittest.skipUnless(
        importlib.machinery.FrozenImporter.find_spec("os") is not None,
        "selected interpreter does not freeze os",
    )
    def test_ca21_frozen_precedence_ignores_project_shadow(self):
        shadow = self.write(self.root / "os.py", "import absent_frozen_shadow_plugin\n")
        result = invoke(self.python_request("import os\n"))
        self.assertTrue(result["ok"], result)
        self.assertNotIn(str(shadow), result["sourceRequirements"]["files"])

    @unittest.skipUnless(sys.platform == "darwin", "Mach-O linkage requires Darwin")
    def test_ca21_transitive_native_stdlib_distribution_refuses_even_with_linkage(self):
        library_source = self.write(
            self.root / "library.c", "int fixture(void) { return 0; }\n"
        )
        library = self.external / "libstdlib-fixture.dylib"
        extension_source = self.write(
            self.root / "extension.c",
            "int fixture(void); int stdlib_fixture(void) { return fixture(); }\n",
        )
        extension = self.external / "_tkinter.so"
        for command in (
            [
                "/usr/bin/cc",
                "-dynamiclib",
                "-install_name",
                str(library),
                str(library_source),
                "-o",
                str(library),
            ],
            [
                "/usr/bin/cc",
                "-dynamiclib",
                str(extension_source),
                str(library),
                "-o",
                str(extension),
            ],
        ):
            subprocess.run(command, capture_output=True, text=True, check=True)
        request = self.python_request("import turtle\n")
        result = invoke(request)
        self.assertFalse(result["ok"], result)
        self.assertIn(
            "stdlib native distribution outside runtime roots: _tkinter",
            result["error"],
        )

    def test_ca21_reviewed_startup_hook_binds_shadowed_imports(self):
        hook = self.write(
            self.root / "reviewed_sitecustomize.py", REVIEWED_HOMEBREW_HOOK
        )
        self.assertEqual(
            hashlib.sha256(hook.read_bytes()).hexdigest(),
            "1a773d37457f89ca5d3b7c96541eb8e32e72e47d6c6d48b6428d81e3e7ddafff",
        )
        shadow = self.write(self.external / "re.py", "VALUE = 1\n")
        analyzer = (
            MODULE.read_text()
            .split("const code = String.raw`\n", 1)[1]
            .split("\n`;", 1)[0]
        )
        program = (
            "import json,sys\nnamespace={}\nexec(compile("
            + repr(analyzer)
            + ", '<production import analyzer>', 'exec'), namespace)\n"
            + "namespace['required']=set(); namespace['seen']=set()\n"
            + "namespace['startup_hooks'].add(sys.argv[4])\n"
            + "namespace['visit'](sys.argv[4],[sys.argv[5],*sys.path],sys.argv[1],[],name='sitecustomize',flags={},project=False)\n"
            + "print(json.dumps(sorted(namespace['required'])))\n"
        )
        result = subprocess.run(
            [
                self.python,
                "-I",
                "-B",
                "-c",
                program,
                str(self.root),
                "[]",
                '["python"]',
                str(hook),
                str(self.external),
            ],
            env=self.env,
            cwd=self.base,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn(str(shadow), json.loads(result.stdout.splitlines()[-1]))

    def test_ca22_loader_literals_use_command_cwd_and_symlinks_refuse(self):
        self.write(self.root / "loaded.py", "VALUE = 1\n")
        self.write(self.root / "sub/loaded.py", "import external_plugin\n")
        plugin = self.write(self.external / "external_plugin.py", "VALUE = 1\n")
        request = self.python_request("import runpy\nrunpy.run_path('loaded.py')\n")
        request["commands"][0]["cwd"] = str(self.root / "sub")
        result = invoke(request)
        self.assertTrue(result["ok"], result)
        self.assertIn(
            str(plugin),
            {
                file
                for requirement in result["requirements"]
                for file in requirement["files"]
            },
        )
        target = self.write(self.root / "vendor/gate/check.py", "import helper\n")
        entry = self.root / "tools/check.py"
        entry.parent.mkdir()
        entry.symlink_to(target)
        request["commands"][0]["subject"][1] = str(entry)
        result = invoke(request)
        self.assertFalse(result["ok"], result)
        self.assertIn("symlinked Python source", result["error"])

    def test_ca23_bound_native_wrappers_do_not_skip_python(self):
        script = self.write(self.root / "check.py", "VALUE = 1\n")
        launcher = self.root / "launcher"
        launcher.symlink_to("/usr/bin/true")
        policy = {
            "toolchains": [
                declaration("python", "python-runtime", [self.python]),
                {
                    "id": "wrapper",
                    "kind": "executable",
                    "locator": {"mode": "path", "value": str(launcher)},
                    "requires": ["python"],
                    "version_command": None,
                    "version_cwd": None,
                    "accept": {"sha256": [], "version_contains": []},
                },
            ],
            "recipes": [],
            "preflight": [],
            "claim_checker": {
                "command": [str(launcher), self.python, str(script)],
                "cwd": ".",
                "toolchain": ["wrapper"],
            },
        }
        result = invoke(
            {
                "op": "capture",
                "root": str(self.root),
                "env": self.env,
                "policy": policy,
                "ids": ["wrapper"],
            }
        )
        self.assertFalse(result["ok"], result)
        self.assertIn("Python command wrapper", result["error"])

    def test_ca18_plain_runtime_declarations_require_family_adapters(self):
        for runtime, family in (
            (self.python, "python-runtime"),
            (shutil.which("node"), "node-toolchain"),
        ):
            with self.subTest(runtime=runtime):
                if runtime is None:
                    raise RuntimeError("Runtime family fixture requires Node")
                tool = {
                    "id": "runtime",
                    "kind": "executable",
                    "locator": {"mode": "path", "value": runtime},
                    "requires": [],
                    "version_command": None,
                    "version_cwd": None,
                    "accept": {"sha256": [], "version_contains": []},
                }
                request = {
                    "op": "bound",
                    "root": str(self.root),
                    "env": self.env,
                    "ids": ["runtime"],
                    "command": [
                        runtime,
                        "-c" if family == "python-runtime" else "-e",
                        "",
                    ],
                    "policy": {
                        "toolchains": [tool],
                        "recipes": [],
                        "preflight": [],
                        "claim_checker": {"toolchain": []},
                    },
                }
                result = invoke(request)
                self.assertFalse(result["ok"], result)
                self.assertIn(family, result["error"])
                directory = self.root / family
                directory.mkdir()
                selected = directory / (
                    "python3" if family == "python-runtime" else "node"
                )
                shutil.copyfile(runtime, selected)
                selected.chmod(0o755)
                alias = directory / "runtime-alias"
                os.link(selected, alias)
                request["env"] = {
                    **self.env,
                    "PATH": str(directory) + os.pathsep + self.env["PATH"],
                }
                request["command"][0] = str(alias)
                tool["locator"]["value"] = str(alias)
                result = invoke(request)
                self.assertFalse(result["ok"], result)
                self.assertIn(family, result["error"])
                if family == "node-toolchain":
                    request["env"]["NODE_OPTIONS"] = "--require /unbound/preload.js"
                    result = invoke(request)
                    self.assertFalse(result["ok"], result)
                    self.assertIn("NODE_OPTIONS", result["error"])

    def test_quint_family_gate_tracks_installed_cli_and_subcommand(self):
        package = self.external / "quint-package"
        cli = self.write(
            package / "dist/cli.js", "#!/usr/bin/env node\n", executable=True
        )
        internal = self.write(
            package / "dist/internal.js", "#!/usr/bin/env node\n", executable=True
        )
        self.write(
            package / "package.json",
            json.dumps(
                {
                    "name": "@informalsystems/quint",
                    "version": "1.0.0",
                    "bin": {"quint": "dist/cli.js"},
                }
            ),
        )
        alias = self.root / "selected-tool"
        alias.symlink_to(cli)
        package_tool = {
            "id": "package",
            "kind": "tree",
            "locator": {"mode": "path", "value": str(package)},
            "requires": [],
            "version_command": None,
            "version_cwd": None,
            "accept": {"sha256": [], "version_contains": []},
        }
        request = {
            "op": "bound",
            "root": str(self.root),
            "env": self.env,
            "ids": ["package"],
            "command": [str(alias), "typecheck", "model.qnt"],
            "policy": {
                "toolchains": [package_tool],
                "recipes": [],
                "preflight": [],
                "claim_checker": {"toolchain": []},
            },
        }
        result = invoke(request)
        self.assertFalse(result["ok"], result)
        self.assertIn("matching quint-backends", result["error"])
        request["policy"]["toolchains"].append(
            declaration(
                "family", "quint-backends", [str(alias), "verify"], requires=["package"]
            )
        )
        request["ids"] = ["family"]
        result = invoke(request)
        self.assertFalse(result["ok"], result)
        self.assertIn("matching quint-backends", result["error"])
        for command in (
            [shutil.which("node"), str(cli), "verify"],
            [str(internal), "verify"],
        ):
            request["command"] = command
            result = invoke(request)
            self.assertFalse(result["ok"], result)
            self.assertIn("Quint wrapper or package-internal", result["error"])

    def test_rustup_hardlinks_are_recognized_by_identity(self):
        binary = self.root / "bin/rustup"
        binary.parent.mkdir()
        shutil.copyfile("/usr/bin/true", binary)
        binary.chmod(0o755)
        cargo = binary.with_name("cargo")
        os.link(binary, cargo)
        request = {
            "op": "rustup-proxy",
            "root": str(self.root),
            "env": self.env,
            "command": str(cargo),
        }
        result = invoke(request)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["proxy"], result)
        cargo.unlink()
        shutil.copyfile("/usr/bin/true", cargo)
        cargo.chmod(0o755)
        result = invoke(request)
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["proxy"], result)

    def test_python_sibling_loaders_and_snapshot_restore_bind_imports(self):
        self.write(self.root / "loaded.py", "import external_plugin\n")
        module = self.write(self.external / "external_plugin.py", "VALUE = 1\n")
        sources = (
            "import importlib.util\nfrom pathlib import Path\nspec = importlib.util.spec_from_file_location('loaded', Path(__file__).with_name('loaded.py'))\nmodule = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(module)\n",
            "import runpy\nfrom pathlib import Path\nrunpy.run_path(str(Path(__file__).parent / 'loaded.py'))\n",
            "import runpy, sys\nfrom pathlib import Path\ndef load():\n sys.argv = [str(Path(__file__).with_name('loaded.py')), '--fixture']\n runpy.run_path(sys.argv[0], run_name='__main__')\n",
            "import runpy, sys\nfrom pathlib import Path\ndef load():\n previous = sys.path[:]\n try:\n  sys.path.insert(0, str(Path(__file__).resolve().parent))\n  return runpy.run_path(str(Path(__file__).with_name('loaded.py')))\n finally:\n  sys.path[:] = previous\n",
        )
        for source in sources:
            with self.subTest(source=source):
                result = invoke(self.python_request(source))
                self.assertTrue(result["ok"], result)
                self.assertIn(
                    str(module),
                    {
                        file
                        for requirement in result["requirements"]
                        for file in requirement["files"]
                    },
                )
                rejected = self.capture_python(source)
                self.assertFalse(rejected["ok"], rejected)
                self.assertIn("external_plugin.py", rejected["error"])

    def test_python_loader_preserves_search_path_and_run_name(self):
        self.write(
            self.root / "plugins/loaded.py",
            "if __name__ == '<run_path>':\n import external_plugin\n",
        )
        self.write(self.root / "plugins/external_plugin.py", "VALUE = 'shadow'\n")
        external = self.write(self.external / "external_plugin.py", "VALUE = 1\n")
        result = invoke(
            self.python_request("import runpy\nrunpy.run_path('plugins/loaded.py')\n")
        )
        self.assertTrue(result["ok"], result)
        files = {
            file
            for requirement in result["requirements"]
            for file in requirement["files"]
        }
        self.assertIn(str(external), files)
        self.assertNotIn(str(self.root / "plugins/external_plugin.py"), files)
        external.unlink()
        fallback = invoke(
            self.python_request("import runpy\nrunpy.run_path('plugins/loaded.py')\n")
        )
        self.assertTrue(fallback["ok"], fallback)
        inputs = {
            file
            for requirement in fallback["requirements"]
            for file, _digest in requirement.get("inputs", [])
        }
        self.assertIn(str(self.root / "plugins/external_plugin.py"), inputs)

    def test_python_argv_loader_requires_unchanged_straightline_selection(self):
        self.write(self.root / "loaded.py", "VALUE = 1\n")
        mutations = (
            "sys.argv[0] = selected",
            "sys.argv.append(selected)",
            "if condition:\n  sys.argv = [selected]",
            "for value in values:\n  sys.argv = [value]",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                body = "\n".join(" " + line for line in mutation.splitlines())
                source = (
                    "import runpy, sys\ndef load():\n sys.argv = ['loaded.py']\n"
                    + body
                    + "\n runpy.run_path(sys.argv[0])\n"
                )
                result = invoke(self.python_request(source))
                self.assertFalse(result["ok"], result)
                self.assertIn("Python loader location", result["error"])

    def test_python_wrapper_command_context_refuses(self):
        request = self.python_request("VALUE = 1\n")
        wrapper = self.write(
            self.root / "run.sh", "exec " + shlex.quote(self.python) + " check.py\n"
        )
        request["commands"][0]["subject"] = ["/bin/sh", str(wrapper)]
        result = invoke(request)
        self.assertFalse(result["ok"], result)
        self.assertIn("Python command wrapper", result["error"])

    def test_python_dependency_of_bound_quint_is_not_a_python_invocation(self):
        binary = self.root / "quint"
        binary.symlink_to("/usr/bin/true")
        script = self.write(self.root / "check.py", "VALUE = 1\n")
        runtime = declaration("python", "python-runtime", [self.python])
        commands = []
        for identifier, executable in (("quint", str(binary)), ("bash", "/bin/bash")):
            commands.append(
                {
                    "id": identifier,
                    "kind": "executable",
                    "locator": {"mode": "path", "value": executable},
                    "requires": ["python"],
                    "version_command": None,
                    "version_cwd": None,
                    "accept": {"sha256": [], "version_contains": []},
                }
            )
        policy = {
            "toolchains": [runtime, *commands],
            "recipes": [],
            "preflight": [
                {"command": [str(binary), "verify"], "cwd": ".", "toolchain": ["quint"]}
            ],
            "claim_checker": {
                "command": [self.python, str(script)],
                "cwd": ".",
                "toolchain": ["python"],
            },
        }
        request = {
            "op": "capture",
            "root": str(self.root),
            "env": self.env,
            "ids": ["quint"],
            "policy": policy,
        }
        result = invoke(request)
        self.assertTrue(result["ok"], result)
        policy["preflight"][0] = {
            "command": ["/bin/bash", "-c", shlex.quote(self.python) + " check.py"],
            "cwd": ".",
            "toolchain": ["bash"],
        }
        request["ids"] = ["bash"]
        rejected = invoke(request)
        self.assertFalse(rejected["ok"], rejected)
        self.assertIn("Python command wrapper", rejected["error"])

    def test_node_runtime_option_overrides_refuse(self):
        for name in ("NODE_OPTIONS", "npm_config_node_options"):
            for value in (
                "--require /opt/hooks/trace.js",
                "--import=external-loader",
                "--loader x",
                "-rhook",
                "--max-old-space-size=1024",
            ):
                with self.subTest(name=name, value=value):
                    result = invoke(
                        {
                            "op": "node",
                            "root": str(self.root),
                            "env": {**self.env, name: value},
                            "declaration": declaration(
                                "node", "node-toolchain", ["pnpm", "exec", "tsx"]
                            ),
                        }
                    )
                    self.assertFalse(result["ok"], result)
                    self.assertIn(name, result["error"])

    def test_macho_embedded_loader_environment_refuses(self):
        result = invoke(
            {
                "op": "macho",
                "root": str(self.root),
                "env": self.env,
                "text": "Load command 0\n cmd LC_DYLD_ENVIRONMENT\n cmdsize 64\n name DYLD_LIBRARY_PATH=/opt/override (offset 12)\n",
            }
        )
        self.assertFalse(result["ok"], result)
        self.assertIn("LC_DYLD_ENVIRONMENT", result["error"])

    def test_unresolved_dynamic_python_imports_reject(self):
        sources = (
            "import importlib\ndef load(name):\n return importlib.import_module(name)\n",
            "def load(name):\n return __import__(name)\n",
            "from importlib import import_module as load\ndef selected(name):\n return load(name)\n",
            "import builtins\ndef load(name):\n return builtins.__import__(name)\n",
            "from builtins import __import__ as load\ndef selected(name):\n return load(name)\n",
            "import importlib\ndef load(name):\n try:\n  return importlib.import_module(name)\n except ImportError:\n  return None\n",
        )
        for source in sources:
            with self.subTest(source=source):
                result = invoke(self.python_request(source))
                self.assertFalse(result["ok"], result)
                self.assertIn("unresolved dynamic Python import", result["error"])

    def test_guarded_startup_import_absence_is_revalidated(self):
        startup = self.write(
            self.external / "sitecustomize.py",
            "try:\n import optional_startup_external\nexcept ImportError:\n pass\n",
        )
        script = self.write(self.root / "check.py", "VALUE = 1\n")
        optional = self.external / "optional_startup_external.py"
        runtime = declaration(
            "python", "python-runtime", [self.python], requires=["startup-hook"]
        )
        hook = {
            "id": "startup-hook",
            "kind": "file",
            "locator": {"mode": "path", "value": str(startup)},
            "requires": [],
            "version_command": None,
            "version_cwd": None,
            "accept": {"sha256": [], "version_contains": []},
        }
        result = invoke(
            {
                "op": "optional-install",
                "root": str(self.root),
                "env": {**self.env, "PYTHONPATH": str(self.external)},
                "policy": {
                    "toolchains": [runtime, hook],
                    "recipes": [],
                    "preflight": [],
                    "claim_checker": {
                        "command": [self.python, str(script)],
                        "cwd": ".",
                        "toolchain": ["python"],
                    },
                },
                "ids": ["python"],
                "install_file": str(optional),
            }
        )
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["accepted"], result)
        self.assertIn(
            "Installed tool selection or bytes changed: python", result["error"]
        )
        self.write(
            self.external / "guarded_package/__init__.py", "import escaped_dependency\n"
        )
        self.write(self.external / "escaped_dependency.py", "VALUE = 3\n")
        rejected = invoke(
            self.python_request(
                "try:\n import guarded_package.child\nexcept ImportError:\n pass\n"
            )
        )
        self.assertFalse(rejected["ok"], rejected)
        self.assertIn("guarded_package.child", rejected["error"])

    def test_literal_dynamic_python_import_binds_module(self):
        module = self.write(self.external / "dynamic_external.py", "VALUE = 1\n")
        result = invoke(
            self.python_request(
                "import importlib\nimportlib.import_module('dynamic_external')\n"
            )
        )
        self.assertTrue(result["ok"], result)
        files = {
            file
            for requirement in result["requirements"]
            for file in requirement["files"]
        }
        self.assertIn(str(module), files)

    def test_python_parent_initializers_and_from_submodules_are_bound(self):
        parent = self.write(self.external / "outer/__init__.py", "\n")
        child = self.write(self.external / "outer/inner/__init__.py", "\n")
        leaf = self.write(self.external / "outer/inner/sub.py", "VALUE = 1\n")
        result = invoke(self.python_request("from outer.inner import sub\n"))
        self.assertTrue(result["ok"], result)
        files = {
            file
            for requirement in result["requirements"]
            for file in requirement["files"]
        }
        self.assertTrue({str(parent), str(child), str(leaf)} <= files, files)

    def test_python_metadata_imports_do_not_execute_cwd_modules(self):
        marker = self.base / "executed-project-module"
        for name in ("json", "ast", "sitecustomize"):
            self.write(
                self.root / (name + ".py"),
                "open(" + repr(str(marker)) + ", 'w').write('executed')\n",
            )
        result = invoke(self.python_request("VALUE = 1\n"))
        self.assertFalse(marker.exists(), result)
        self.assertTrue(result["ok"], result)
        request = self.python_request("VALUE = 1\n")
        request["env"]["PYTHONUSERBASE"] = str(self.base / "userbase")
        query = subprocess.run(
            [
                self.python,
                "-I",
                "-c",
                "import json,site,sys; print(json.dumps({'site':site.getusersitepackages(),'allowed':sys.prefix==sys.base_prefix or sys.base_prefix in site.PREFIXES}))",
            ],
            cwd=self.base,
            env=request["env"],
            capture_output=True,
            text=True,
            check=True,
        )
        user = json.loads(query.stdout)
        if user["allowed"]:
            self.write(
                Path(user["site"]) / "startup.pth",
                "import pathlib; pathlib.Path("
                + repr(str(marker))
                + ").write_text('executed')\n",
            )
            result = invoke(request)
            self.assertFalse(marker.exists(), result)
            self.assertFalse(result["ok"], result)
            self.assertIn("Python user-site startup", result["error"])

    def node_request(self, *, hidden=False):
        node = shutil.which("node")
        if not node:
            raise RuntimeError("Node toolchain fixture requires Node")
        self.node = str(Path(node).resolve())
        probe = subprocess.run(
            [
                self.node,
                "-p",
                "JSON.stringify({bun:!!process.versions.bun,cache:typeof require('node:module').enableCompileCache==='function'})",
            ],
            cwd=self.base,
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        )
        capability = json.loads(probe.stdout)
        if capability["bun"] or not capability["cache"]:
            raise RuntimeError(
                "Node fixture requires genuine Node with module.enableCompileCache; Bun compatibility mode is unsupported"
            )
        self.bin = self.base / "bin"
        self.bin.mkdir()
        (self.bin / "node").symlink_to(self.node)
        manager = self.base / "pnpm-distribution"
        self.write(
            manager / "package.json",
            json.dumps(
                {"name": "pnpm", "version": "1.0.0", "bin": {"pnpm": "bin/pnpm.cjs"}}
            ),
        )
        manager_entry = self.write(
            manager / "bin/pnpm.cjs",
            """#!/usr/bin/env node
const cp=require('node:child_process'),path=require('node:path');
const args=process.argv.slice(2);
if(args[0]==='--version'){console.log('1.0.0');}
else if(args[0]==='config'&&args[1]==='get'&&args[2]==='node-options'){
 const fs=require('node:fs'),file=path.join(process.cwd(),'.npmrc');
 const config=fs.existsSync(file)?fs.readFileSync(file,'utf8'):'';
 console.log(/^node-options=(.*)$/m.exec(config)?.[1]??'undefined');
}
else if(args[0]==='exec'){
 const child=cp.spawnSync(args[1],args.slice(2),{stdio:'inherit',env:{...process.env,PATH:path.join(process.cwd(),'node_modules','.bin')+path.delimiter+process.env.PATH}});
 if(child.error)throw child.error;process.exit(child.status??1);
}else{throw Error('unsupported fixture pnpm invocation');}
""",
            executable=True,
        )
        (self.bin / "pnpm").symlink_to(manager_entry)
        dev = {"tsx": "1.0.0", **({"hidden": "1.0.0"} if hidden else {})}
        self.write(
            self.root / "package.json",
            json.dumps(
                {
                    "name": "fixture",
                    "packageManager": "pnpm@1.0.0",
                    "devDependencies": dev,
                }
            ),
        )
        lock = "lockfileVersion: '9.0'\nimporters:\n  .:\n    devDependencies:\n"
        for name in dev:
            lock += f"      {name}:\n        specifier: 1.0.0\n        version: 1.0.0\n"
        lock += "snapshots:\n" + "".join(f"  {name}@1.0.0: {{}}\n" for name in dev)
        self.write(self.root / "pnpm-lock.yaml", lock)
        self.write(
            self.root / "node_modules/tsx/package.json",
            json.dumps(
                {"name": "tsx", "version": "1.0.0", "bin": {"tsx": "dist/cli.mjs"}}
            ),
        )
        self.write(
            self.root / "node_modules/tsx/dist/cli.mjs",
            "#!/usr/bin/env node\nexport {};\n",
            executable=True,
        )
        self.write(
            self.root / "node_modules/tsx/dist/cache.cjs",
            'exports.tmpdir=require("node:os").tmpdir();\n',
        )
        if hidden:
            self.write(
                self.root / "node_modules/hidden/package.json",
                json.dumps({"name": "hidden", "version": "1.0.0"}),
            )
            self.write(
                self.root / "node_modules/hidden/index.js", "module.exports=1;\n"
            )
        self.injected = self.base / "shim-modules"
        self.injected.mkdir()
        self.write(self.injected / "injected.js", "module.exports=1;\n")
        self.shim = self.write(
            self.root / "node_modules/.bin/tsx",
            SHIM.replace("__PATH__", str(self.injected)),
            executable=True,
        )
        self.preferred_node = self.write(
            self.root / "node_modules/.bin/node",
            "#!/bin/sh\nexec " + shlex.quote(self.node) + ' "$@"\n',
            executable=True,
        )
        self.write(self.root / "entry.ts", "export {};\n")
        return {
            "op": "node",
            "root": str(self.root),
            "env": {**self.env, "PATH": str(self.bin) + os.pathsep + self.env["PATH"]},
            "hash": True,
            "declaration": declaration(
                "node",
                "node-toolchain",
                [str(self.bin / "pnpm"), "exec", "tsx", "entry.ts"],
            ),
        }

    def test_ca25_pnpm_node_options_refuse_before_exec_preload(self):
        request = self.node_request()
        hook = self.write(
            self.external / "preload.cjs",
            "require('node:fs').writeFileSync("
            + json.dumps(str(self.base / "unbound-preload-executed"))
            + ", 'executed');\n",
        )
        self.write(self.root / ".npmrc", "node-options=--require " + str(hook) + "\n")
        result = invoke(request)
        self.assertFalse(result["ok"], result)
        self.assertIn("pnpm-injected Node runtime selectors", result["error"])
        self.assertFalse((self.base / "unbound-preload-executed").exists())

    def test_ca05_preferred_node_wrapper_preloads_refuse_before_execution(self):
        request = self.node_request()
        marker = self.base / "unbound-preferred-preload-executed"
        hook = self.write(
            self.external / "preferred-preload.cjs",
            "require('node:fs').writeFileSync("
            + json.dumps(str(marker))
            + ", 'executed');\n",
        )
        for source in (
            "#!/bin/sh\nexec "
            + shlex.quote(self.node)
            + " --require "
            + shlex.quote(str(hook))
            + ' "$@"\n',
            "#!/bin/sh\nexport NODE_OPTIONS="
            + shlex.quote("--require " + str(hook))
            + "\nexec "
            + shlex.quote(self.node)
            + ' "$@"\n',
            "#!/bin/sh\nUNMODELED=1\nexec " + shlex.quote(self.node) + ' "$@"\n',
        ):
            with self.subTest(source=source):
                self.preferred_node.write_text(source, encoding="utf-8")
                result = invoke(request)
                self.assertFalse(result["ok"], result)
                self.assertIn(
                    "Unsupported preferred Node runtime wrapper", result["error"]
                )
                self.assertFalse(marker.exists())

    def test_pnpm_shim_mutation_invalidates_or_rejects(self):
        request = self.node_request()
        before = invoke(request)
        self.assertTrue(before["ok"], before)
        self.shim.write_text(self.shim.read_text() + "# changed launcher\n")
        after = invoke(request)
        self.assertTrue(not after["ok"] or after["digest"] != before["digest"], after)

    def test_pnpm_preferred_node_and_injected_node_path_are_bound(self):
        request = self.node_request()
        before = invoke(request)
        self.assertTrue(before["ok"], before)
        self.preferred_node.write_text(
            self.preferred_node.read_text() + "# changed preferred runtime\n"
        )
        runtime_changed = invoke(request)
        self.assertTrue(runtime_changed["ok"], runtime_changed)
        self.assertNotEqual(before["digest"], runtime_changed["digest"])
        self.write(self.injected / "injected.js", "module.exports=2;\n")
        path_changed = invoke(request)
        self.assertTrue(path_changed["ok"], path_changed)
        self.assertNotEqual(runtime_changed["digest"], path_changed["digest"])

    def test_pnpm_virtual_store_links_are_bound_without_allowing_store_escape(self):
        request = self.node_request()
        store = self.root / "node_modules/.pnpm"
        modules = store / "tsx@1.0.0/node_modules"
        modules.mkdir(parents=True)
        package = modules / "tsx"
        (self.root / "node_modules/tsx").rename(package)
        (self.root / "node_modules/tsx").symlink_to(
            os.path.relpath(package, self.root / "node_modules"),
            target_is_directory=True,
        )
        dependency = store / "esbuild@1.0.0/node_modules/esbuild"
        self.write(
            dependency / "package.json",
            json.dumps(
                {
                    "name": "esbuild",
                    "version": "1.0.0",
                    "dependencies": {"backend": "1.0.0"},
                }
            ),
        )
        implementation = self.write(dependency / "index.js", "module.exports=1;\n")
        backend = store / "backend@1.0.0/node_modules/backend"
        self.write(
            backend / "package.json",
            json.dumps({"name": "backend", "version": "1.0.0"}),
        )
        backend_implementation = self.write(backend / "index.js", "module.exports=1;\n")
        (dependency.parent / "backend").symlink_to(
            os.path.relpath(backend, dependency.parent), target_is_directory=True
        )
        unrelated = self.write(
            store / "unrelated@1.0.0/node_modules/unrelated/index.js",
            "module.exports=1;\n",
        )
        (unrelated.parent / "outside").symlink_to(
            self.external, target_is_directory=True
        )
        hoisted = store / "node_modules"
        hoisted.mkdir()
        for link in (modules / "esbuild", hoisted / "esbuild"):
            link.symlink_to(
                os.path.relpath(dependency, link.parent), target_is_directory=True
            )
        self.shim.write_text(
            SHIM.replace(
                "__PATH__", os.pathsep.join(map(str, (modules, hoisted, self.injected)))
            ),
            encoding="utf-8",
        )
        before = invoke(request)
        self.assertTrue(before["ok"], before)
        link = next(
            file
            for file in before["files"]
            if file["path"] == "execution/node-path/0/esbuild"
        )
        self.assertEqual(link["kind"], "symlink-directory")
        self.assertTrue(
            link["resolved_path"].startswith("execution/node-store/0/"), link
        )
        self.assertFalse(
            any("unrelated@" in file["path"] for file in before["files"]), before
        )
        unrelated.write_text("module.exports=2;\n", encoding="utf-8")
        retained = invoke(request)
        self.assertTrue(retained["ok"], retained)
        self.assertEqual(before["digest"], retained["digest"])
        backend_implementation.write_text("module.exports=2;\n", encoding="utf-8")
        dependency_changed = invoke(request)
        self.assertTrue(dependency_changed["ok"], dependency_changed)
        self.assertNotEqual(retained["digest"], dependency_changed["digest"])
        implementation.write_text("module.exports=2;\n", encoding="utf-8")
        changed = invoke(request)
        self.assertTrue(changed["ok"], changed)
        self.assertNotEqual(dependency_changed["digest"], changed["digest"])
        (modules / "esbuild").unlink()
        (modules / "esbuild").symlink_to(
            os.path.relpath(self.injected, modules), target_is_directory=True
        )
        escaped = invoke(request)
        self.assertFalse(escaped["ok"], escaped)
        self.assertIn("Tool symlink escapes root boundary", escaped["error"])

    def test_tsx_typescript_parent_selects_ts_before_js(self):
        request = self.node_request(hidden=True)
        self.write(self.root / "entry.ts", "import './dependency.js';\n")
        self.write(self.root / "dependency.js", "export {};\n")
        self.write(self.root / "dependency.ts", "import 'hidden';\n")
        result = invoke(request)
        self.assertTrue(result["ok"], result)
        self.assertTrue(
            any(root["label"] == "packages/hidden/1.0.0" for root in result["roots"]),
            result,
        )

    def test_ambiguous_js_parent_substitution_rejects(self):
        request = self.node_request()
        self.write(self.root / "entry.ts", "import './parent.js';\n")
        self.write(self.root / "parent.js", "import './dependency.js';\n")
        self.write(self.root / "dependency.js", "export {};\n")
        self.write(self.root / "dependency.ts", "export {};\n")
        result = invoke(request)
        self.assertFalse(result["ok"], result)
        self.assertIn("Ambiguous Node source import", result["error"])

    @unittest.skipUnless(sys.platform == "darwin", "Mach-O discovery requires Darwin")
    def test_native_capture_and_revalidation_are_stable(self):
        from evidence_v4_fixture import EvidenceV4Fixture

        with EvidenceV4Fixture() as fixture:
            result = invoke(
                {
                    "op": "stability",
                    "root": str(fixture.root),
                    "env": fixture.policy["environment"]["set"],
                    "policy": fixture.policy,
                    "ids": ["native"],
                }
            )
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["identities"], result["after"])

    @unittest.skipUnless(sys.platform == "darwin", "Mach-O discovery requires Darwin")
    def test_concurrent_native_capture_and_revalidation_are_stable(self):
        from evidence_v4_fixture import EvidenceV4Fixture

        with EvidenceV4Fixture() as first, EvidenceV4Fixture() as second:
            # Keep producer inputs fixed for both concurrent owners.
            producer = self.base / "producer/tools"
            shutil.copytree(REPO / "tools/evidence-v4", producer / "evidence-v4")
            shutil.copy2(REPO / "tools/evidence-run.ts", producer / "evidence-run.ts")
            module = producer / "evidence-v4/evidence-v4-toolchain.ts"
            aliases = self.base / "metadata-aliases"
            aliases.mkdir()
            (aliases / "otool").symlink_to("/usr/bin/otool")
            second.policy["environment"]["set"]["PATH"] = (
                str(aliases) + os.pathsep + second.policy["environment"]["set"]["PATH"]
            )
            requests = [
                {
                    "op": "stability",
                    "root": str(fixture.root),
                    "env": fixture.policy["environment"]["set"],
                    "policy": fixture.policy,
                    "ids": ["native"],
                    "iterations": 30,
                    "real_native": True,
                    "module": module.as_uri(),
                }
                for fixture in (first, second)
            ]
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(invoke, requests))
            selected = subprocess.run(
                ["/usr/bin/xcrun", "--no-cache", "--find", "otool"],
                env=first.policy["environment"]["set"],
                capture_output=True,
                text=True,
                check=True,
            )
            backend_hash = (
                "sha256:"
                + hashlib.sha256(Path(selected.stdout.strip()).read_bytes()).hexdigest()
            )
            for result in results:
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["identities"], result["after"])
                native = next(
                    identity
                    for identity in result["identities"]
                    if identity["id"] == "native"
                )
                self.assertTrue(
                    any(file.get("hash") == backend_hash for file in native["files"]),
                    native,
                )
            inner = self.external / "selected/inner"
            inner.mkdir(parents=True)
            executable = self.write(
                self.external / "selected/tool", "#!/bin/sh\nexit 0\n", executable=True
            )
            twin = executable.with_name("twin")
            os.link(executable, twin)
            (self.root / "directory-alias").symlink_to(inner, target_is_directory=True)
            entry = self.root / "entry"
            entry.symlink_to("directory-alias/../tool")
            resolved = invoke(
                {
                    "op": "resolve",
                    "module": module.as_uri(),
                    "root": str(self.root),
                    "env": self.env,
                    "commands": [str(entry), str(twin)],
                }
            )
            self.assertTrue(resolved["ok"], resolved)
            self.assertEqual(
                [value["realpath"] for value in resolved["selected"]],
                [str(executable), str(twin)],
            )

    def test_loader_overrides_reject_during_discovery(self):
        image = self.write(self.root / "image", "native fixture\n", executable=True)
        for name in (
            "DYLD_INSERT_LIBRARIES",
            "DYLD_LIBRARY_PATH",
            "DYLD_FRAMEWORK_PATH",
            "DYLD_FALLBACK_LIBRARY_PATH",
            "__XPC_DYLD_LIBRARY_PATH",
        ):
            with self.subTest(name=name):
                result = invoke(
                    {
                        "op": "native",
                        "root": str(self.root),
                        "env": {**self.env, name: str(self.external)},
                        "declaration": declaration(
                            "native", "darwin-native", [str(image)]
                        ),
                    }
                )
                self.assertFalse(result["ok"], result)
                self.assertIn(name, result["error"])

    @unittest.skipUnless(sys.platform == "darwin", "Mach-O discovery requires Darwin")
    def test_nonadapter_darwin_dylib_closure_is_bound_without_version_probe(self):
        library_source = self.write(
            self.root / "library.c", "int fixture(void) { return 0; }\n"
        )
        library = self.external / "libfixture.dylib"
        executable_source = self.write(
            self.root / "main.c",
            "int fixture(void); int main(void) { return fixture(); }\n",
        )
        executable = self.external / "fixture"
        for command in (
            [
                "/usr/bin/cc",
                "-dynamiclib",
                "-install_name",
                str(library),
                str(library_source),
                "-o",
                str(library),
            ],
            [
                "/usr/bin/cc",
                str(executable_source),
                str(library),
                "-o",
                str(executable),
            ],
        ):
            subprocess.run(command, capture_output=True, text=True, check=True)
        for kind in ("executable", "file"):
            with self.subTest(kind=kind):
                tool = {
                    "id": "fixture",
                    "kind": kind,
                    "locator": {"mode": "path", "value": str(executable)},
                    "requires": [],
                    "version_command": None,
                    "version_cwd": None,
                    "accept": {"sha256": [], "version_contains": []},
                }
                request = {
                    "op": "capture",
                    "root": str(self.root),
                    "env": self.env,
                    "ids": ["fixture"],
                    "policy": {
                        "toolchains": [tool],
                        "recipes": [],
                        "preflight": [],
                        "claim_checker": {"toolchain": []},
                    },
                }
                result = invoke(request)
                self.assertTrue(result["ok"], result)
                identity = next(
                    value for value in result["identities"] if value["id"] == "fixture"
                )
                self.assertEqual(identity["kind"], "tree")
                self.assertTrue(
                    any(file["path"] == "selected-file" for file in identity["files"])
                )
                self.assertTrue(
                    any(
                        file["path"].startswith("native/non-system-libraries/")
                        for file in identity["files"]
                    )
                )
                request.update(
                    op="optional-install", install_file=str(library), append=True
                )
                changed = invoke(request)
                self.assertTrue(changed["ok"], changed)
                self.assertFalse(changed["accepted"], changed)
                self.assertIn(
                    "Installed tool selection or bytes changed: fixture",
                    changed["error"],
                )

    def _tree_capture_request(self, directory):
        return {
            "op": "capture",
            "root": str(self.root),
            "env": self.env,
            "ids": ["fixture"],
            "policy": {
                "toolchains": [
                    {
                        "id": "fixture",
                        "kind": "tree",
                        "locator": {"mode": "path", "value": str(directory)},
                        "requires": [],
                        "version_command": None,
                        "version_cwd": None,
                        "accept": {"sha256": [], "version_contains": []},
                    }
                ],
                "recipes": [],
                "preflight": [],
                "claim_checker": {"toolchain": []},
            },
        }

    @unittest.skipUnless(sys.platform == "darwin", "Mach-O discovery requires Darwin")
    def test_ca24_tree_external_library_mutation_refuses_unbound_launch_context(self):
        distribution = self.external / "distribution"
        executable = distribution / "bin/child"
        executable.parent.mkdir(parents=True)
        library = self.external / "libfixture.dylib"
        library_source = self.write(
            self.root / "library.c", "int fixture(void) { return 0; }\n"
        )
        executable_source = self.write(
            self.root / "main.c",
            "int fixture(void); int main(void) { return fixture(); }\n",
        )
        for install, rpath in (
            (str(library), None),
            ("@loader_path/../../libfixture.dylib", None),
            ("@executable_path/../../libfixture.dylib", None),
            ("@rpath/libfixture.dylib", None),
            ("@rpath/libfixture.dylib", str(self.external)),
        ):
            with self.subTest(install=install, rpath=rpath):
                subprocess.run(
                    [
                        "/usr/bin/cc",
                        "-dynamiclib",
                        "-install_name",
                        install,
                        str(library_source),
                        "-o",
                        str(library),
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                subprocess.run(
                    [
                        "/usr/bin/cc",
                        str(executable_source),
                        str(library),
                        *([f"-Wl,-rpath,{rpath}"] if rpath else []),
                        "-o",
                        str(executable),
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                request = self._tree_capture_request(distribution)
                # A separately bound matching library cannot supply missing launch semantics.
                request["policy"]["toolchains"][0]["requires"] = ["library"]
                request["policy"]["toolchains"].append(
                    {
                        "id": "library",
                        "kind": "file",
                        "locator": {"mode": "path", "value": str(library)},
                        "requires": [],
                        "version_command": None,
                        "version_cwd": None,
                        "accept": {"sha256": [], "version_contains": []},
                    }
                )
                for changed in (False, True):
                    with self.subTest(changed=changed):
                        if changed:
                            with library.open("ab") as stream:
                                stream.write(b"\0")
                        result = invoke(request)
                        self.assertFalse(result["ok"], result)
                        self.assertIn(
                            "Unbound native tree launch context", result["error"]
                        )
                        self.assertIn(install, result["error"])
                        self.assertIn(str(executable), result["error"])

    @unittest.skipUnless(sys.platform == "darwin", "Mach-O discovery requires Darwin")
    def test_ca24_system_only_go_shaped_tree_preserves_all_payloads(self):
        distribution = self.external / "distribution"
        images = [
            distribution / "bin/go",
            distribution / "bin/gofmt",
            *(
                distribution / "pkg/tool/darwin_arm64" / name
                for name in (
                    "asm",
                    "cgo",
                    "compile",
                    "cover",
                    "link",
                    "preprofile",
                    "vet",
                )
            ),
            distribution / "pkg/tool/darwin_arm64/cc",
        ]
        for image in images:
            image.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy("/usr/bin/true", image)
        request = self._tree_capture_request(distribution)
        request["policy"]["toolchains"][0]["locator"] = {
            "mode": "command-relative",
            "value": str(distribution / "bin/go"),
            "parent_levels": 1,
            "subpath": ".",
        }
        request["op"] = "stability"
        result = invoke(request)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["identities"], result["after"])
        identity = next(
            value for value in result["identities"] if value["id"] == "fixture"
        )
        self.assertEqual(identity["kind"], "tree")
        files = {entry["path"] for entry in identity["files"]}
        self.assertTrue(
            {str(image.relative_to(distribution)) for image in images} <= files
        )
        inspected = {
            probe["command"][-1]
            for probe in identity["discovery"]
            if len(probe["command"]) == 3 and probe["command"][1] == "-l"
        }
        self.assertTrue({str(image) for image in images} <= inspected)
        self.assertFalse(
            any(
                probe["command"][0] in {str(image) for image in images}
                for probe in identity["discovery"]
            ),
            identity["discovery"],
        )

    @unittest.skipUnless(sys.platform == "darwin", "Mach-O discovery requires Darwin")
    def test_ca24_native_free_quint_shaped_tree_preserves_script_aliases(self):
        package = self.external / "package"
        cli = self.write(
            package / "dist/src/cli.js", "#!/usr/bin/env node\n", executable=True
        )
        self.write(package / "package.json", '{"name":"fixture","version":"1.0.0"}\n')
        alias = package / "quint"
        alias.symlink_to("dist/src/cli.js")
        request = self._tree_capture_request(package)
        request["policy"]["toolchains"][0]["locator"] = {
            "mode": "command-relative",
            "value": str(cli),
            "parent_levels": 2,
            "subpath": ".",
        }
        request["op"] = "stability"
        result = invoke(request)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["identities"], result["after"])
        identity = next(
            value for value in result["identities"] if value["id"] == "fixture"
        )
        files = {entry["path"]: entry for entry in identity["files"]}
        self.assertEqual(files["quint"]["kind"], "symlink-file")
        self.assertEqual(files["quint"]["resolved_path"], "dist/src/cli.js")
        self.assertFalse(
            any(str(package) in probe["command"] for probe in identity["discovery"]),
            identity["discovery"],
        )

    def test_rust_commands_require_toolchain_family(self):
        for driver, args, family in (
            ("cargo", ["test"], "cargo-toolchain"),
            ("rustc", ["input.rs"], "cargo-toolchain"),
            ("cargo", ["kani"], "kani-toolchain"),
        ):
            with self.subTest(driver=driver, args=args):
                command = self.root / driver
                if not command.exists():
                    command.symlink_to("/usr/bin/true")
                tool = {
                    "id": "driver",
                    "kind": "executable",
                    "locator": {"mode": "path", "value": str(command)},
                    "requires": [],
                    "version_command": None,
                    "version_cwd": None,
                    "accept": {"sha256": [], "version_contains": []},
                }
                result = invoke(
                    {
                        "op": "bound",
                        "root": str(self.root),
                        "env": self.env,
                        "ids": ["driver"],
                        "command": [str(command), *args],
                        "policy": {
                            "toolchains": [tool],
                            "recipes": [],
                            "preflight": [],
                            "claim_checker": {"toolchain": []},
                        },
                    }
                )
                self.assertFalse(result["ok"], result)
                self.assertIn(family, result["error"])

    @unittest.skipUnless(sys.platform == "darwin", "Mach-O discovery requires Darwin")
    def test_rustup_selected_version_driver_is_bound(self):
        self._assert_rustup_selected_driver_bound("cargo", hardlink=False)

    @unittest.skipUnless(sys.platform == "darwin", "Mach-O discovery requires Darwin")
    def test_rustup_hardlinked_selected_drivers_are_bound(self):
        for driver in ("cargo", "rustc"):
            with self.subTest(driver=driver):
                self._assert_rustup_selected_driver_bound(driver, hardlink=True)

    def _assert_rustup_selected_driver_bound(self, driver, *, hardlink):
        directory = self.base / ("rustup-bin-" + driver)
        installed = self.external / ("selected-" + driver)
        shutil.copyfile("/usr/bin/true", installed)
        installed.chmod(0o755)
        self.write(
            directory / "rustup",
            "#!/bin/sh\nif [ \"$1\" = which ]; then printf '%s\\n' "
            + shlex.quote(str(installed))
            + "; else printf '"
            + driver
            + " 1.0\\n'; fi\n",
            executable=True,
        )
        if hardlink:
            os.link(directory / "rustup", directory / driver)
        else:
            (directory / driver).symlink_to("rustup")
        tool = {
            "id": driver,
            "kind": "executable",
            "locator": {"mode": "command", "value": driver},
            "requires": ["shell"],
            "version_command": [driver, "--version"],
            "version_cwd": ".",
            "accept": {"sha256": [], "version_contains": []},
        }
        shell = {
            "id": "shell",
            "kind": "file",
            "locator": {"mode": "path", "value": "/bin/sh"},
            "requires": [],
            "version_command": None,
            "version_cwd": None,
            "accept": {"sha256": [], "version_contains": []},
        }
        request = {
            "op": "capture",
            "root": str(self.root),
            "env": {**self.env, "PATH": str(directory) + os.pathsep + self.env["PATH"]},
            "ids": [driver],
            "policy": {
                "toolchains": [tool, shell],
                "recipes": [],
                "preflight": [],
                "claim_checker": {"toolchain": []},
            },
        }
        result = invoke(request)
        self.assertTrue(result["ok"], result)
        identity = next(
            value for value in result["identities"] if value["id"] == driver
        )
        self.assertEqual(identity["kind"], "tree")
        self.assertTrue(
            any(
                file["path"] == f"native/drivers/{driver}-0"
                for file in identity["files"]
            )
        )
        files = {file["path"]: file for file in identity["files"]}
        self.assertEqual(
            files["selected-file"]["hash"],
            "sha256:" + hashlib.sha256((directory / driver).read_bytes()).hexdigest(),
        )
        self.assertEqual(
            files[f"native/drivers/{driver}-0"]["hash"],
            "sha256:" + hashlib.sha256(installed.read_bytes()).hexdigest(),
        )
        self.assertTrue(
            any(
                probe["command"] == [str(directory / "rustup"), "which", driver]
                for probe in identity["discovery"]
            )
        )
        request.update(op="optional-install", install_file=str(installed), append=True)
        changed = invoke(request)
        self.assertTrue(changed["ok"], changed)
        self.assertFalse(changed["accepted"], changed)
        self.assertIn(
            "Installed tool selection or bytes changed: " + driver, changed["error"]
        )

    @unittest.skipUnless(sys.platform == "darwin", "Mach-O discovery requires Darwin")
    def test_nonadapter_metadata_helpers_use_producer_binding(self):
        tool = {
            "id": "true",
            "kind": "executable",
            "locator": {"mode": "path", "value": "/usr/bin/true"},
            "requires": [],
            "version_command": ["/usr/bin/true"],
            "version_cwd": ".",
            "accept": {"sha256": [], "version_contains": []},
        }
        result = invoke(
            {
                "op": "stability",
                "root": str(self.root),
                "env": self.env,
                "ids": ["true"],
                "policy": {
                    "toolchains": [tool],
                    "recipes": [],
                    "preflight": [],
                    "claim_checker": {"toolchain": []},
                },
            }
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["identities"], result["after"])
        identity = next(
            value for value in result["identities"] if value["id"] == "true"
        )
        self.assertEqual(identity["kind"], "executable")
        self.assertEqual([file["path"] for file in identity["files"]], ["."])

    @unittest.skipUnless(sys.platform == "darwin", "Mach-O discovery requires Darwin")
    def test_metadata_helper_requires_captured_byte_binding(self):
        helper = self.write(
            self.external / "version-helper",
            "#!/bin/sh\nprintf '1.0\\n'\n",
            executable=True,
        )
        tools = [
            {
                "id": "main",
                "kind": "executable",
                "locator": {"mode": "path", "value": "/usr/bin/true"},
                "requires": [],
                "version_command": [str(helper)],
                "version_cwd": ".",
                "accept": {"sha256": [], "version_contains": []},
            },
            {
                "id": "helper",
                "kind": "file",
                "locator": {"mode": "path", "value": str(helper)},
                "requires": [],
                "version_command": None,
                "version_cwd": None,
                "accept": {"sha256": [], "version_contains": []},
            },
            {
                "id": "shell",
                "kind": "file",
                "locator": {"mode": "path", "value": "/bin/sh"},
                "requires": [],
                "version_command": None,
                "version_cwd": None,
                "accept": {"sha256": [], "version_contains": []},
            },
        ]
        request = {
            "op": "capture",
            "root": str(self.root),
            "env": self.env,
            "ids": ["main", "shell"],
            "policy": {
                "toolchains": tools,
                "recipes": [],
                "preflight": [],
                "claim_checker": {"toolchain": []},
            },
        }
        rejected = invoke(request)
        self.assertFalse(rejected["ok"], rejected)
        self.assertIn(str(helper), rejected["error"])
        request["ids"] = ["main", "helper", "shell"]
        accepted = invoke(request)
        self.assertTrue(accepted["ok"], accepted)

        alias = self.external / "helper-hardlink"
        os.link(helper, alias)
        tools[1]["locator"]["value"] = str(alias)
        linked = invoke(request)
        self.assertTrue(linked["ok"], linked)
        bound = invoke({**request, "op": "bound", "command": [str(helper)]})
        self.assertTrue(bound["ok"], bound)

        copied = self.external / "helper-copy"
        shutil.copy2(helper, copied)
        tools[1]["locator"]["value"] = str(copied)
        rejected_copy = invoke(request)
        self.assertFalse(rejected_copy["ok"], rejected_copy)
        self.assertIn(str(helper), rejected_copy["error"])

    @unittest.skipUnless(sys.platform == "darwin", "Mach-O discovery requires Darwin")
    def test_metadata_helper_bytes_enter_producer_identity(self):
        helpers = self.base / "helpers"
        otool = self.write(
            helpers / "otool",
            "#!/bin/sh\nprintf 'Load command 0\\n cmd LC_UUID\\n'\n",
            executable=True,
        )
        plutil = self.write(
            helpers / "plutil",
            '#!/bin/sh\nprintf \'{"Version":"1.0"}\\n\'\n',
            executable=True,
        )
        sdk = self.base / "sdk"
        self.write(
            sdk / "SDKSettings.plist", "<?xml version='1.0'?><plist><dict/></plist>\n"
        )
        request = {
            "op": "capture",
            "root": str(self.root),
            "env": {
                **self.env,
                "PATH": str(helpers) + os.pathsep + self.env["PATH"],
                "SDKROOT": str(sdk),
            },
            "policy": {
                "toolchains": [],
                "recipes": [],
                "preflight": [],
                "claim_checker": {"toolchain": []},
            },
            "ids": [],
        }
        before = invoke(request)
        self.assertTrue(before["ok"], before)
        runtime_hash = (
            "sha256:"
            + hashlib.sha256(Path("/bin/sh").resolve().read_bytes()).hexdigest()
        )
        self.assertTrue(
            any(
                file.get("hash") == runtime_hash
                for file in before["identities"][0]["files"]
            ),
            before,
        )
        self.assertTrue(
            any(
                probe["command"][0] == str(otool) and probe["command"][-1] == "/bin/sh"
                for probe in before["identities"][0]["discovery"]
            ),
            before["identities"][0]["discovery"],
        )
        for helper in (otool, plutil):
            with self.subTest(helper=helper.name):
                helper.write_text(
                    helper.read_text() + "# different helper bytes, same metadata\n"
                )
                after = invoke(request)
                self.assertTrue(after["ok"], after)
                self.assertNotEqual(
                    before["identities"][0]["digest"], after["identities"][0]["digest"]
                )
                before = after

    def test_python_declarations_do_not_alias_checker_contexts(self):
        first = self.write(self.root / "first.py", "VALUE = 1\n")
        second = self.write(self.root / "second.py", "import second_external\n")
        self.write(self.external / "second_external.py", "VALUE = 2\n")
        tools = [
            declaration(name, "python-runtime", [self.python])
            for name in ("a-python", "b-python")
        ]
        policy = {
            "toolchains": tools,
            "recipes": [],
            "preflight": [
                {
                    "command": [self.python, str(first)],
                    "cwd": ".",
                    "toolchain": ["a-python"],
                }
            ],
            "claim_checker": {
                "command": [self.python, str(second)],
                "cwd": ".",
                "toolchain": ["b-python"],
            },
        }
        result = invoke(
            {
                "op": "capture",
                "root": str(self.root),
                "env": {**self.env, "PYTHONPATH": str(self.external)},
                "policy": policy,
                "ids": ["a-python", "b-python"],
            }
        )
        self.assertFalse(result["ok"], result)
        self.assertIn("second_external.py", result["error"])


if __name__ == "__main__":
    unittest.main()
