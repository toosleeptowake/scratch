from typing import Any, List
from ansible.plugins.lookup import LookupBase
from ansible.errors import AnsibleError
from ansible.template import Templar
import yaml
import os
import base64
import json
import copy

def _recursive_combine(dict1, dict2):
  result = dict1.copy()
  for key, value in dict2.items():
    if (
        key in result
        and isinstance(result[key], dict)
        and isinstance(value, dict)
    ):
      result[key] = _recursive_combine(result[key], value)
    else:
      result[key] = value
  return result

class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        self.set_options(var_options=variables, direct=kwargs)

        merged_data = {}
        combined_dict = {}
        for file_path in terms:
            real_path = self.find_file_in_search_path(variables, 'files', file_path)
            if not real_path:
                raise AnsibleError(f'Could not locate {file_path}')

            with open(real_path, "r") as f:
                parsed_yaml = yaml.safe_load(f) or {}
                combined_dict.update(parsed_yaml)

        def jinja_present(node):
            if isinstance(node, dict):
                # Resolve elements inside the dict individually
                for k, v, in node.items():
                    if jinja_present(v):
                        return True
                return False
            elif isinstance(node, list):
                # Resolve elements inside lists individually
                for v in node:
                    if jinja_present(v):
                        return True
                return False
            elif isinstance(node, str) and ("{{" in node or "{%" in node):
                return True
            else:
                return False

        def template_placeholder(node):
            if isinstance(node, dict):
                # Resolve elements inside the dict individually
                return {k: template_placeholder(v) for k, v in node.items()}
            elif isinstance(node, list):
                # Resolve elements inside lists individually
                return [template_placeholder(item) for item in node]
            elif isinstance(node, str) and ("{{" in node or "{%" in node):
                # Only template actual Jinja strings
                return "placeholder:" + base64.b64encode(node.encode('utf-8')).decode('utf-8')
            else:
                # Numbers, booleans, or plain strings don't need templating
                return node

        override_dict = {}
        if 'override_var' in kwargs and variables:
            if kwargs['override_var'] not in variables:
                raise AnsibleError(f"override var {kwargs['override_var']} does not exist")
            override_dict = variables[kwargs['override_var']]

        combined_dict = _recursive_combine(combined_dict, 
            override_dict
        )


#        combined_dict = _recursive_combine(combined_dict, {
#            'top_one': {
#                'YY': '{{ top_two.environment }}'
#            }
#        })

        max_attempts = 5

        resolved_dict = copy.deepcopy(combined_dict)

        while jinja_present(resolved_dict):
            max_attempts -= 1
            if max_attempts == 0:
                break


            placeholder_dict = template_placeholder(resolved_dict)

            rendering_scope = variables.copy() if variables else {}
            rendering_scope.update(placeholder_dict)

            templar = Templar(loader=self._loader, variables=rendering_scope)

            try:
                resolved_data = templar.template(resolved_dict, fail_on_undefined=True)
            except Exception as e:
                raise AnsibleError(f"Something bad happened e:{e}")

            
            def template_unplaceholder(node):
                if isinstance(node, dict):
                    # Resolve elements inside the dict individually
                    return {k: template_unplaceholder(v) for k, v in node.items()}
                elif isinstance(node, list):
                    # Resolve elements inside lists individually
                    return [template_unplaceholder(item) for item in node]
                elif isinstance(node, str) and node.startswith("placeholder:"):
                    return base64.b64decode(
                        node[len("placeholder:"):]
                    ).decode('utf-8')
                else:
                    # Numbers, booleans, or plain strings don't need templating
                    return node

            resolved_dict = template_unplaceholder(resolved_data)


        merged_data['python_created'] = True
        merged_data['output'] = resolved_dict
        return [merged_data]
#
