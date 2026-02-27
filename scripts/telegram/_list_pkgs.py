import pkg_resources
pkgs = sorted([f'{d.project_name}=={d.version}' for d in pkg_resources.working_set])
for p in pkgs:
    print(p)
