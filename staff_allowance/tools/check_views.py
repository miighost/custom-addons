"""Static check: every field a view references must exist on the model, and
every field used inside a domain must be searchable (stored, or with a
`search=` method). This is the exact class of error that broke install."""
import ast
import glob
import re
import sys

BASE = {"id", "display_name", "create_date", "create_uid", "write_date",
        "write_uid", "__last_update", "active", "sequence", "color",
        "company_id", "name", "message_follower_ids", "message_ids",
        "activity_ids", "message_needaction", "message_attachment_count"}

# models we extend but do not define -- their fields live in core Odoo
EXTERNAL = {"hr.employee", "res.partner"}


REC_NAME = {}


def parse_models(paths):
    """-> {model_name: {field: {'store': bool, 'search': bool}}}, {model: [parents]}"""
    fields, parents = {}, {}
    for path in paths:
        tree = ast.parse(open(path).read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            name = inherit = None
            inherits = []
            own = {}
            rec_name = None
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                        and isinstance(stmt.targets[0], ast.Name):
                    target = stmt.targets[0].id
                    if target == "_rec_name" and isinstance(stmt.value, ast.Constant):
                        rec_name = stmt.value.value
                    elif target == "_name" and isinstance(stmt.value, ast.Constant):
                        name = stmt.value.value
                    elif target == "_inherit":
                        if isinstance(stmt.value, ast.Constant):
                            inherit = stmt.value.value
                            inherits.append(stmt.value.value)
                        elif isinstance(stmt.value, (ast.List, ast.Tuple)):
                            for elt in stmt.value.elts:
                                if isinstance(elt, ast.Constant):
                                    inherits.append(elt.value)
                    elif isinstance(stmt.value, ast.Call):
                        func = stmt.value.func
                        src = ast.unparse(func)
                        if src.startswith("fields."):
                            kwargs = {k.arg: k.value for k in stmt.value.keywords}
                            computed = "compute" in kwargs or "related" in kwargs
                            store = (not computed) or (
                                "related" in kwargs and "store" not in kwargs) or (
                                isinstance(kwargs.get("store"), ast.Constant)
                                and kwargs["store"].value is True)
                            comodel = None
                            if stmt.value.args and isinstance(
                                    stmt.value.args[0], ast.Constant):
                                first = stmt.value.args[0].value
                                if isinstance(first, str) and "." in first:
                                    comodel = first
                            if "comodel_name" in kwargs and isinstance(
                                    kwargs["comodel_name"], ast.Constant):
                                comodel = kwargs["comodel_name"].value
                            if "related" in kwargs and isinstance(
                                    kwargs["related"], ast.Constant):
                                comodel = None
                            own[target] = {
                                "store": bool(store),
                                "search": "search" in kwargs,
                                "comodel": comodel,
                            }
            model = name or inherit
            if not model:
                continue
            fields.setdefault(model, {}).update(own)
            if rec_name:
                REC_NAME[model] = rec_name
            parents.setdefault(model, []).extend(
                i for i in inherits if i != model)
    return fields, parents


def resolve(model, fields, parents, seen=None):
    seen = seen or set()
    if model in seen:
        return {}
    seen.add(model)
    out = dict(fields.get(model, {}))
    for parent in parents.get(model, []):
        for k, v in resolve(parent, fields, parents, seen).items():
            out.setdefault(k, v)
    return out


NESTED = re.compile(
    r'<field name="([a-z_0-9]+)"[^>]*>\s*(<(?:list|tree|form|kanban)\b.*?</(?:list|tree|form|kanban)>)\s*</field>',
    re.S)


def split_nested(arch, known):
    """Pull embedded subviews out of an arch and pair them with their comodel."""
    nested = []
    for match in NESTED.finditer(arch):
        fname, sub = match.group(1), match.group(2)
        meta = known.get(fname) or {}
        if meta.get("comodel"):
            nested.append((meta["comodel"], sub))
    return NESTED.sub("", arch), nested


def check_arch(path, model, arch, fields, parents, problems, external=False):
    known = resolve(model, fields, parents)
    if not known:
        return
    arch, nested = split_nested(arch, known)

    for fname in ([] if external else
                  set(re.findall(r'<field name="([a-z_0-9]+)"', arch))):
        if fname in ("arch", "model", "inherit_id", "priority"):
            continue
        if fname not in known and fname not in BASE:
            problems.append(f"{path}: {model} has no field '{fname}'")

    for domain in re.findall(r'domain="\[([^"]*)\]"', arch):
        for fname in set(re.findall(r"\('([a-z_0-9]+)'", domain)):
            meta = known.get(fname.split(".")[0])
            if meta and not (meta["store"] or meta["search"]):
                problems.append(
                    f"{path}: {model}.{fname} is not stored and has no search "
                    f"method -- cannot be used in a domain")

    for ctx in re.findall(r"'group_by':\s*'([a-z_0-9]+)'", arch):
        meta = known.get(ctx)
        if meta and not meta["store"]:
            problems.append(
                f"{path}: {model}.{ctx} is not stored -- cannot group by it")

    for comodel, sub in nested:
        check_arch(path, comodel, sub, fields, parents, problems,
                   external=comodel in EXTERNAL)


def main():
    fields, parents = parse_models(glob.glob("models/*.py"))
    problems = []

    for path in sorted(glob.glob("views/*.xml")):
        text = open(path).read()
        for record in re.finditer(
                r'<record id="[^"]+" model="ir\.ui\.view">(.*?)</record>',
                text, re.S):
            block = record.group(1)
            model_match = re.search(r'<field name="model">([^<]+)</field>', block)
            if not model_match:
                continue
            model = model_match.group(1)
            known = resolve(model, fields, parents)
            if not known:
                continue

            arch = block.split('type="xml"', 1)[-1]
            check_arch(path, model, arch, fields, parents, problems,
                       external=model in EXTERNAL)

            if "<search" in arch and model not in EXTERNAL:
                known = resolve(model, fields, parents)
                if known:
                    rec = REC_NAME.get(model)
                    for parent in parents.get(model, []):
                        rec = rec or REC_NAME.get(parent)
                    if not rec and "name" not in known:
                        problems.append(
                            f"{path}: {model} has a search view but no `name` "
                            f"field and no _rec_name -- Odoo cannot build the "
                            f"implicit search field")
                    elif rec and rec not in known:
                        problems.append(
                            f"{path}: {model}._rec_name = '{rec}' is not a "
                            f"field on the model")

    # actions carry domains too
    for path in sorted(glob.glob("views/*.xml")):
        text = open(path).read()
        for record in re.finditer(
                r'<record id="[^"]+" model="ir\.actions\.act_window">(.*?)</record>',
                text, re.S):
            block = record.group(1)
            model_match = re.search(r'<field name="res_model">([^<]+)</field>',
                                    block)
            domain_match = re.search(r'<field name="domain">\[([^<]*)\]</field>',
                                     block)
            if not model_match or not domain_match:
                continue
            known = resolve(model_match.group(1), fields, parents)
            for fname in set(re.findall(r"\('([a-z_0-9]+)'", domain_match.group(1))):
                meta = known.get(fname.split(".")[0])
                if meta and not (meta["store"] or meta["search"]):
                    problems.append(
                        f"{path}: action domain uses non-searchable "
                        f"{model_match.group(1)}.{fname}")

    if problems:
        print("PROBLEMS FOUND:")
        for problem in sorted(set(problems)):
            print("  -", problem)
        return 1
    print("View field check: OK")
    return 0


sys.exit(main())
