#!/usr/bin/env python3
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to you under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Generate RST documentation from Kconfig files using kconfiglib.
# Extracts ---help--- sections and creates per-symbol and per-choice pages.
#

import argparse
import operator
import os
import re
import shutil
import sys
import tempfile

import kconfiglib
from jinja2 import Environment, FileSystemLoader


def choice_id(choice):
    return f"choice_{choice.kconfig.unique_choices.index(choice)}"


def choice_desc(choice):
    desc = "choice"
    if choice.name:
        desc += " " + choice.name
    for node in choice.nodes:
        if node.prompt:
            desc += ": " + node.prompt[0]
            break
    return desc


def rst_link(sc):
    if isinstance(sc, kconfiglib.Symbol):
        # For defined symbols with locations, generate a cross-link to the
        # generated per-symbol documentation page.
        if sc.nodes:
            return rf":doc:`CONFIG_{sc.name} </kconfig/CONFIG_{sc.name}>`"
        # For undefined/placeholder symbols, fall back to plain, RST-safe text.
        # In particular, avoid trailing underscores, which docutils interprets
        # as reference markers.
        return sc.name.replace("_", "\\_")
    elif isinstance(sc, kconfiglib.Choice):
        return rf"\ :ref:`<{choice_desc(sc)}> <{choice_id(sc)}>`"
    return kconfiglib.standard_sc_expr_str(sc)


def plain_link(sc):
    """Like rst_link but returns plain CONFIG_name for raw blocks (no RST markup)."""
    if isinstance(sc, kconfiglib.Symbol):
        if sc.nodes:
            return f"CONFIG_{sc.name}"
    elif isinstance(sc, kconfiglib.Choice):
        return choice_desc(sc)
    return kconfiglib.standard_sc_expr_str(sc)


def expr_str(expr):
    return kconfiglib.expr_str(expr, rst_link)


def top_to_node(node):
    path = []
    while node.parent is not node.kconfig.top_node:
        node = node.parent
        path = [node] + path
    return path


def has_non_trivial_dep(sc):
    """Return True if the symbol/choice has a non-trivial direct dependency."""
    if sc.direct_dep is None:
        return False
    return sc.direct_dep is not sc.kconfig.y


def has_rev_dep(sym):
    """Return True if the symbol has a non-trivial reverse dependency."""
    if not hasattr(sym, "rev_dep") or sym.rev_dep is None:
        return False
    return sym.rev_dep is not sym.kconfig.n


def format_default_value(value):
    """Format a default value for safe single-line RST output."""
    if isinstance(value, kconfiglib.Symbol):
        return f"CONFIG_{value.name}"
    if isinstance(value, kconfiglib.Choice):
        return choice_desc(value)
    if value in (0, 1, 2):
        return {0: "n", 1: "m", 2: "y"}[value]
    if isinstance(value, str):
        # Represent empty-string defaults in a way that does not confuse the
        # inline-literal parser (``""`` instead of ````).
        if value == "":
            return '""'
        s = value
    else:
        s = str(value)
    s = s.replace("\n", " ").replace("`", "'").replace("\\", "/").replace("_", "\\_").replace("|", "\\|")
    return s[:100] + ("..." if len(s) > 100 else "")


def escape_help(sc):
    """No-op: help is rendered in a literal block, so no RST escaping needed."""


def setup_stub_dirs(topdir):
    """
    Create temporary directories with stub Kconfig files required by the
    root Kconfig. Returns (bindir, appsdir, externaldir) paths.
    The source tree is never modified.
    """
    tmp = tempfile.mkdtemp(prefix="nuttx_kconfig_docs_")

    bindir = os.path.join(tmp, "bindir")
    os.makedirs(os.path.join(bindir, "arch", "dummy"), exist_ok=True)
    os.makedirs(os.path.join(bindir, "boards", "dummy"), exist_ok=True)
    os.makedirs(os.path.join(bindir, "drivers", "platform"), exist_ok=True)
    for path in [
        os.path.join(bindir, "arch", "dummy", "Kconfig"),
        os.path.join(bindir, "boards", "dummy", "Kconfig"),
        os.path.join(bindir, "drivers", "platform", "Kconfig"),
    ]:
        with open(path, "w") as f:
            f.write("")

    appsdir = os.path.join(tmp, "apps")
    os.makedirs(appsdir, exist_ok=True)
    with open(os.path.join(appsdir, "Kconfig"), "w") as f:
        f.write("")

    externaldir = os.path.join(tmp, "external")
    os.makedirs(externaldir, exist_ok=True)
    with open(os.path.join(externaldir, "Kconfig"), "w") as f:
        f.write("")

    return tmp, bindir, appsdir, externaldir


def main():
    parser = argparse.ArgumentParser(
        description="Generate RST documentation from Kconfig files"
    )
    parser.add_argument(
        "--report-missing",
        action="store_true",
        help="Report CONFIG symbols that have no ---help--- text",
    )
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    topdir = os.path.realpath(os.path.join(script_dir, "..", ".."))

    tmpdir, bindir, appsdir, externaldir = setup_stub_dirs(topdir)
    try:
        # Prepare a stable, RST-safe apps bindir so that defaults derived from
        # $APPSBINDIR do not embed random temporary directory names.
        appsbindir = "/tmp/nuttx-appsbindir"
        os.makedirs(appsbindir, exist_ok=True)
        with open(os.path.join(appsbindir, "Kconfig"), "w") as f:
            f.write("")

        os.environ["TOPDIR"] = topdir
        os.environ["ARCH"] = "dummy"
        os.environ["BINDIR"] = bindir
        os.environ["APPSDIR"] = appsdir
        os.environ["APPSBINDIR"] = appsbindir
        os.environ["EXTERNALDIR"] = externaldir
        os.environ["srctree"] = topdir

        os.chdir(topdir)
        kconf = kconfiglib.Kconfig("Kconfig", warn=False)

        kconfig_rst_dir = os.path.join(topdir, "Documentation", "kconfig")

        # Clean up old files first
        if os.path.exists(kconfig_rst_dir):
            for f in os.listdir(kconfig_rst_dir):
                if f.endswith(".rst"):
                    os.remove(os.path.join(kconfig_rst_dir, f))
        else:
            os.makedirs(kconfig_rst_dir, exist_ok=True)

        env = Environment(loader=FileSystemLoader(script_dir))
        env.globals["kconfiglib"] = kconfiglib
        env.globals["expr_str"] = expr_str
        env.globals["rst_link"] = rst_link
        env.globals["plain_link"] = plain_link
        env.globals["top_to_node"] = top_to_node
        env.globals["choice_desc"] = choice_desc
        env.globals["choice_id"] = choice_id
        env.globals["has_non_trivial_dep"] = has_non_trivial_dep
        env.globals["has_rev_dep"] = has_rev_dep
        env.globals["format_default_value"] = format_default_value

        def safe_desc(sym):
            if sym.nodes and sym.nodes[0].help:
                s = sym.nodes[0].help.split("\n")[0].strip()[:80]
            elif sym.nodes and sym.nodes[0].prompt:
                s = sym.nodes[0].prompt[0][:80]
            else:
                s = "(no description)"
            s = s.replace("*", "\\*").replace("|", "\\|").replace("`", "\\`").replace("_", "\\_")
            if len(s) >= 3 and all(c in "-=_" for c in s):
                return "(no description)"
            return s

        env.globals["safe_desc"] = safe_desc

        def _looks_like_transition(line: str) -> bool:
            stripped = line.strip()
            return (
                len(stripped) >= 4
                and len(set(stripped)) <= 2
                and all(c in "-=*`^_~#+<>" for c in stripped)
            )

        def safe_line(line):
            text = line.expandtabs(8)
            # Indent EVERYTHING by at least 3 spaces.
            # Blank lines must have spaces to keep the literal block alive.
            if not text.strip():
                return "   "

            if _looks_like_transition(text):
                text = f"(separator) {text.strip()}"

            return "   " + text

        def render_help(sc):
            if not sc.nodes or not sc.nodes[0].help:
                return "*No help available*"
            lines = [safe_line(l) for l in sc.nodes[0].help.splitlines()]
            return "::\n\n" + "\n".join(lines)

        def render_kconfig_definition(sc):
            res = []
            for node in sc.nodes:
                header = f"**Definition** ({node.filename}:{node.linenr}):"
                lines = [safe_line(l) for l in node.custom_str(plain_link).splitlines()]
                res.append(header + "\n::\n\n" + "\n".join(lines))
            return "\n\n".join(res)

        env.globals["render_help"] = render_help
        env.globals["render_kconfig_definition"] = render_kconfig_definition

        _type_to_str = getattr(kconfiglib, "TYPE_TO_STR", {})
        env.globals["type_str"] = lambda sc: _type_to_str.get(
            getattr(sc, "orig_type", None), "unknown"
        )

        sym_template = env.get_template("sym.jinja")
        choice_template = env.get_template("choice.jinja")
        index_template = env.get_template("index.jinja")

        missing_help = []

        for sym in kconf.unique_defined_syms:
            escape_help(sym)
            if args.report_missing and not any(n.help for n in sym.nodes):
                missing_help.append(f"CONFIG_{sym.name}")
            with open(
                os.path.join(kconfig_rst_dir, f"CONFIG_{sym.name}.rst"), "w"
            ) as rst_f:
                rst_f.write(":orphan:\n\n")
                rst_f.write(sym_template.render(sym=sym))

        for choice in kconf.unique_choices:
            escape_help(choice)
            with open(
                os.path.join(kconfig_rst_dir, f"{choice_id(choice)}.rst"), "w"
            ) as rst_f:
                rst_f.write(":orphan:\n\n")
                rst_f.write(choice_template.render(choice=choice))

        with open(os.path.join(kconfig_rst_dir, "index.rst"), "w") as rst_f:
            rst_f.write(
                index_template.render(
                    syms=sorted(
                        kconf.unique_defined_syms,
                        key=operator.attrgetter("name"),
                    ),
                )
            )

        if args.report_missing and missing_help:
            print("CONFIG symbols without ---help--- text:", file=sys.stderr)
            for name in sorted(missing_help):
                print(f"  {name}", file=sys.stderr)
            print(
                f"\nTotal: {len(missing_help)} symbols",
                file=sys.stderr,
            )

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
