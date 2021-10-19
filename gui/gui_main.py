from tkinter.filedialog import askopenfilename
import pyvista as pv
from pathlib import Path

class GuiMain:

    # File tab
    def import_mesh(self, resample=False):
        self.plotter.clear()  # clears mesh space every time a new mesh is added
        self.file_path = Path(askopenfilename(title="Select file to open",
                                         filetypes=(("Mesh files", "*.ply"),
                                                    ("all files", "*.*"))))

        self.file_name = self.file_path.name + self.file_path.suffix
        self.extension = self.file_path.suffix
        self.mesh_file = pv.read(self.file_path)

        try:
            self.plotter.add_mesh(self.mesh_file, rgba=True, show_edges=True)
        except:
            self.plotter.add_mesh(self.mesh_file, color='white', show_edges=True)

        self.plotter.reset_camera()
        self.plotter.show_grid()
        self.landmarks = [[], [], []]

    def clean_mesh(self):
        self.plotter.clear()
        try:
            self.plotter.add_mesh(self.mesh_file, rgba=True, show_edges=True)
        except:
            self.plotter.add_mesh(self.mesh_file, color='white', show_edges=True)