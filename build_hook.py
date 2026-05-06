from hatchling.builders.hooks.plugin.interface import BuildHookInterface
import subprocess
from pathlib import Path

class Hook(BuildHookInterface):
    def initialize(self, version, build_data):
        """
        runs before each build
        """
        print("Building frontend assets")
        subprocess.run(['npm', 'run' ,'build'], cwd='./Metarec-ui')

        print("Packaging frontend assets")
        target = self.target_name
        if target == 'wheel':
            output_dir = Path('./Metarec-backend/src/metarec')
            build_data['force_include']['./Metarec-ui/dist'] = output_dir / 'frontend-dist'
        elif target == 'sdist':
            build_data['force_include']['./Metarec-ui/dist'] = 'Metarec-ui/dist'
    
    def finalize(self, version, build_data, artifact_path):
        """
        runs after build
        will not run if --hooks-only is passed to build
        """
        return
