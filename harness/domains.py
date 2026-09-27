"""Explicit current-owner selection inside registered preservation domains."""
import json
from pathlib import Path

import yaml

FORMATS = {'.md', '.yaml', '.yml', '.json'}


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        try:
            if key in result:
                raise ValueError(f'Duplicate structured key: {key}')
            result[key] = value
        except TypeError as exc:
            raise ValueError('Structured mapping keys must be scalar values') from exc
    return result


class StructuredLoader(yaml.SafeLoader):
    pass


def structured_mapping(loader, node):
    return unique_pairs((loader.construct_object(key), loader.construct_object(value))
                        for key, value in node.value)


StructuredLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, structured_mapping)


def fields(value, required, optional=()):
    if (not isinstance(value, dict) or not required <= value.keys()
            or value.keys() - required - set(optional)):
        raise ValueError('Domain selector has missing or unknown fields')


def collection_schema(collection):
    fields(collection, {'registry', 'items', 'path_field', 'where', 'include', 'exclude'},
           {'fallback_path_field', 'strip_prefix'})
    for field in ('items', 'path_field', 'fallback_path_field'):
        if field in collection and (not isinstance(collection[field], str) or not collection[field]):
            raise ValueError(f'Domain collection {field} must be a nonempty string')
    if not isinstance(collection.get('strip_prefix', ''), str):
        raise ValueError('Domain strip_prefix must be a string')
    conditions = collection['where']
    if (not isinstance(conditions, dict) or not conditions
            or any(not isinstance(k, str) or not k or not isinstance(v, list) or not v
                   or any(not isinstance(state, str) or not state for state in v)
                   for k, v in conditions.items())):
        raise ValueError('Domain collection requires named fields with nonempty allowed string states')
    # Validate even when the registry has no currently eligible records.
    for field in ('include', 'exclude'):
        if not isinstance(collection[field], list):
            raise ValueError('Domain include/exclude must be lists')
        for pattern in collection[field]:
            relative(pattern)


def relative(value):
    if (not isinstance(value, str) or not value or Path(value).is_absolute()
            or '..' in Path(value).parts or Path(value).as_posix() != value):
        raise ValueError('Domain paths and patterns must be normalized relative paths')
    return value


def inside(base, value):
    path = base / relative(value)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != base and base in p.parents):
        raise ValueError('Domain selection cannot follow symlinks')
    path.resolve().relative_to(base.resolve())
    return path


def select(base, include, exclude):
    if not isinstance(include, list) or not isinstance(exclude, list):
        raise ValueError('Domain include/exclude must be lists')
    selected, omitted = set(), set()
    for patterns, result in ((include, selected), (exclude, omitted)):
        for pattern in patterns:
            pattern = relative(pattern)
            # A trailing ** denotes files recursively, not only directories.
            if pattern.endswith('/**'):
                pattern += '/*'
            for path in base.glob(pattern):
                name = path.relative_to(base).as_posix()
                inside(base, name)
                if path.is_file() and path.suffix in FORMATS and not any(p.startswith('.') for p in Path(name).parts):
                    result.add(path)
    return selected - omitted


def paths(root):
    from harness.documents import protected_roots
    config = root / '.local/harness/projects.json'
    if not config.exists():
        return []
    settings = json.loads(config.read_text())
    domains = settings.get('current_domains', [])
    if not isinstance(domains, list):
        raise ValueError('current_domains must be a list')
    protected = protected_roots(root)
    result = set()
    seen = set()
    for domain in domains:
        fields(domain, {'root', 'include', 'exclude'}, {'collections'})
        if domain['root'] not in protected:
            raise ValueError('Current domain must be an explicitly registered protected root')
        if domain['root'] in seen:
            raise ValueError('Current domain roots must be unique')
        seen.add(domain['root'])
        base = inside(root, domain['root'])
        if not base.is_dir():
            raise ValueError('Current domain root must exist as a directory')
        domain_result = select(base, domain['include'], [])
        collections = domain.get('collections', [])
        if not isinstance(collections, list):
            raise ValueError('Domain collections must be a list')
        for collection in collections:
            collection_schema(collection)
            registry = inside(base, collection['registry'])
            data = yaml.load(registry.read_text(), Loader=StructuredLoader)
            records = data.get(collection['items']) if isinstance(data, dict) else None
            if not isinstance(records, list):
                raise ValueError('Domain collection requires a registry record list')
            conditions = collection['where']
            for record in records:
                if not isinstance(record, dict):
                    raise ValueError('Domain registry records must be mappings')
                if not all(record.get(field) in allowed for field, allowed in conditions.items()):
                    continue
                locator = record.get(collection['path_field'])
                if locator is None and collection.get('fallback_path_field'):
                    locator = record.get(collection['fallback_path_field'])
                prefix = collection.get('strip_prefix', '')
                if not isinstance(locator, str) or not isinstance(prefix, str) or not locator.startswith(prefix):
                    raise ValueError('Active domain record requires a valid current owner path')
                owner = inside(base, locator[len(prefix):])
                if not owner.is_file():
                    raise ValueError(f'Active domain owner is missing: {owner.relative_to(root)}')
                domain_result.update(select(owner.parent, collection['include'], collection['exclude']))
        result.update(domain_result - select(base, domain['exclude'], []))
    return sorted(result)


def sections(path, raw):
    """Keep structured records separate so one excerpt does not mix several claims."""
    if path.suffix == '.json':
        data = json.loads(raw, object_pairs_hook=unique_pairs)
    else:
        data = yaml.load(raw.decode('utf-8'), Loader=StructuredLoader)
    if not isinstance(data, (dict, list)):
        raise ValueError(f'Current structured owner requires a mapping or list: {path}')
    groups = data.items() if isinstance(data, dict) else [('records', data)]
    for key, value in groups:
        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            for number, item in enumerate(value):
                label = item.get('id', item.get('name', number))
                yield f'{key}/{label}', yaml.safe_dump(item, allow_unicode=True, sort_keys=False)
        else:
            yield str(key), yaml.safe_dump({key: value}, allow_unicode=True, sort_keys=False)
