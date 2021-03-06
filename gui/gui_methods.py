"""
Created on Mon Aug 2, 2021
@author: TAbdelAlim
"""

from tkinter.filedialog import askopenfilename, asksaveasfilename
import os, datetime
import pyacvd
import pyvista as pv
import numpy as np
from pymeshfix import _meshfix
from pathlib import Path
from craniometrics.craniometrics import CranioMetrics
from registration.picking import CoordinatePicking
from registration.write_ply import write_ply_file


class GuiMethods:
    def __init__(self):
        self.mesh_color = 'ivory'
        self.template_color = 'saddlebrown'
        self.template_path = Path('./template/clipped_template_ntplane_com.ply')


    # File tab
    def import_mesh(self, resample=False):
        self.plotter.clear()  # clears mesh space every time a new mesh is added

        self.file_path = Path(askopenfilename(title="Select file to open",
                                         filetypes=(("Mesh files", ("*.ply","*.obj", "*.stl")),
                                                    ("all files", "*.*"))))
        try:
            self.file_name = self.file_path.name #returns name.suffix
            self.extension = self.file_path.suffix
            self.mesh_file = pv.read(self.file_path)
            self.plotter.add_mesh(self.mesh_file, color=self.mesh_color, show_edges=True)

            self.plotter.reset_camera()
            self.plotter.show_grid()
            self.landmarks = [[], [], []]
        except:
            pass

    def clean_mesh(self):
        self.plotter.clear()
        self.plotter.add_mesh(self.mesh_file, color=self.mesh_color, show_edges=True)


    def mesh_edges(self, show=True, opacity=1):
        self.plotter.clear()
        if show == False:
            opacity=0.8

        self.plotter.add_mesh(self.mesh_file, color=self.mesh_color, show_edges=show, opacity = opacity)


    def resample_repair(self, n_vertices=20000, repair=False):
        resampled_path = self.file_path.with_name(self.file_path.stem + '_rs.ply') #+ self.extension for source ext
        GuiMethods.repairsample(self.file_path, postfix='_rs', n_vertices=n_vertices, repair=repair)
        self.file_path = resampled_path


    @staticmethod
    def call_template(ICV_scaling=1):
        template_path = Path('./template/clipped_template_ntplane_com.ply')
        template_mesh = pv.read(template_path)
        template_mesh.points *= ICV_scaling ** (1 / 3) # template_volume = 2339070.752133594
        return template_mesh

    def show_registration(self):
        self.plotter.clear()

        try:
            template_mesh = GuiMethods.call_template(ICV_scaling=self.mesh_file.volume / 2339070.75)
            self.plotter.add_mesh(template_mesh, color=self.template_color, opacity=0.2, show_edges=False)
            GuiMethods.three_slices(template_mesh, self.plotter, self.template_color)

            self.plotter.add_mesh(self.mesh_file, color=self.mesh_color, show_edges=False, opacity=0.2)
            GuiMethods.three_slices(self.mesh_file, self.plotter, self.mesh_color)

            self.plotter.add_legend(labels=[['template', self.template_color], ['mesh', self.mesh_color]],
                                    face='circle')

        except AttributeError:
            template_mesh = GuiMethods.call_template()
            self.plotter.add_mesh(template_mesh, color=self.template_color, opacity=0.2, show_edges=False)
            GuiMethods.three_slices(template_mesh, self.plotter, self.template_color)

            self.plotter.add_legend(labels=[['template',self.template_color]], face='circle')

    @staticmethod
    def three_slices(mesh_file, plotter, color='yellow'):
        AX_slice = mesh_file.slice(normal=[0, 0, 1], origin=[0, 0, 2])
        COR_slice = mesh_file.slice(normal=[0, 1, 0], origin=[0, 0, 2])
        SAG_slice = mesh_file.slice(normal=[1, 0, 0], origin=[0, 0, 2])

        plotter.add_mesh(AX_slice, color=color)
        plotter.add_points(AX_slice.center_of_mass(), color=color, point_size=20, render_points_as_spheres=True)
        plotter.add_mesh(COR_slice, color=color)
        plotter.add_points(COR_slice.center_of_mass(), color=color, point_size=20, render_points_as_spheres=True)
        plotter.add_mesh(SAG_slice, color=color)
        plotter.add_points(SAG_slice.center_of_mass(), color=color, point_size=20, render_points_as_spheres=True)


    @staticmethod
    def repairsample(file_path, n_vertices, postfix = '', repair=False, extension=".ply"):
        remesh = pv.read(file_path)

        if remesh.n_points <= 150000:
            clus = pyacvd.Clustering(remesh)
            clus.subdivide(3)
            clus.cluster(n_vertices)
            remesh = clus.create_mesh()

        elif remesh.n_points > 150000:
            print('Mesh contains too many vertices ({}). Mesh is not resampled.'.format(remesh.n_points))


        remesh_path = file_path.with_name(file_path.stem + postfix + extension)
        write_ply_file(remesh, remesh_path)

        if repair == True:
            _meshfix.clean_from_file(str(remesh_path), str(remesh_path))


    # Reg tab
    def coordinate_picking(self, target):
        metrics = CoordinatePicking(self.file_path)
        metrics.picking(self.plotter, target)
        if target == 'nose':
            self.landmarks[0] = metrics.nose_coord
        elif target == 'left':
            self.landmarks[1] = metrics.left_coord
        elif target == 'right':
            self.landmarks[2] = metrics.right_coord

        if len(self.landmarks[0]) == len(self.landmarks[1]) == len(self.landmarks[2]) == 3:
            return self.landmarks

    def register(self, landmarks, n_iterations = 50, CoM_translation=True):
        metrics = CoordinatePicking(self.file_path)

        # first iteration based on selected landmarks
        metrics.reg_to_template(landmarks)
        self.mesh_file.translate(metrics.translation)
        self.mesh_file.rotate_z(metrics.z_rotation)
        self.mesh_file.rotate_y(metrics.y_rotation)
        self.mesh_file.rotate_x(metrics.x_rotation)


        for i in range(n_iterations):
            metrics.reg_to_template(metrics.lm_surf.points)
            self.mesh_file.translate(metrics.translation)
            self.mesh_file.rotate_z(metrics.z_rotation)
            self.mesh_file.rotate_y(metrics.y_rotation)
            self.mesh_file.rotate_x(metrics.x_rotation)

        if str(self.file_path).endswith('_rg'+ self.extension) or str(self.file_path).endswith('_C'+ self.extension):
            #self.mesh_file.save(str(self.file_path).replace(self.extension, ".ply"))
            write_ply_file(self.mesh_file, str(self.file_path).replace(self.extension, ".ply"))
        elif str(self.file_path).endswith('_rg.ply') or str(self.file_path).endswith('_C.ply'):
            write_ply_file(self.mesh_file, str(self.file_path))
        else:
            #self.mesh_file.save(self.file_path.with_name(self.file_path.stem+'_rg.ply'))
            write_ply_file(self.mesh_file, self.file_path.with_name(self.file_path.stem+'_rg.ply'))
            self.file_path = self.file_path.with_name(self.file_path.stem+'_rg.ply')


        if CoM_translation == True:
            # if False: the centroid of the 3 landmarks is used as the origin in the frame of reference.
            # if True: the mesh is translated along the y-axis (front-back) based on the center of mass of the HC slice
            self.com_translation()

        # # replace old with new registered mesh
        self.plotter.clear()  # clears mesh space every time a new mesh is added
        self.file_name = Path(self.file_path).stem
        self.mesh_file = pv.read(self.file_path)
        self.newpos_landmarks = metrics.lm_surf.points

        self.plotter.add_mesh(self.mesh_file, color=self.mesh_color, opacity=0.5, show_edges=True)
        self.plotter.reset_camera()

        ## show registration
        GuiMethods.three_slices(self.mesh_file, self.plotter, self.mesh_color)

        template_mesh = pv.read(Path("./template/origin_template_ntplane_com.ply"))
        self.plotter.add_mesh(template_mesh, color=self.template_color, opacity=0.1)
        GuiMethods.three_slices(template_mesh, self.plotter, self.template_color)
        self.plotter.add_legend(labels=[['template', self.template_color], ['mesh', self.mesh_color]], face='circle')


        # # write initial landmarks to text
        txtpath = str(self.file_path.parent.joinpath(self.file_name+'_landmarks.txt'))
        if os.path.exists(txtpath):
            mode = "a"
        else:
            mode = "w+"

        f = open(txtpath, mode)
        f.write("\n"+"\n" + 'Registration ' + str(datetime.datetime.now()) + "\n")
        f.write('Initial position landmarks:' + "\n")
        f.write(str(self.landmarks)+"\n")
        f.write('Finial position landmarks:' + "\n")
        new_lndmks = str([np.array(self.newpos_landmarks[0]), np.array(self.newpos_landmarks[1]), np.array(self.newpos_landmarks[2])])
        f.write(str(new_lndmks))
        f.close()


    # Translation
    def com_translation(self):
        temp_metric = CranioMetrics(self.file_path) # temporary metric of the mesh
        temp_metric.extract_dimensions(temp_metric.slice_height)
        trans_y = temp_metric.HC_s.center_of_mass()[1]
        self.mesh_file.translate([0, -trans_y, 0])

        if str(self.file_path).endswith('_rg'+ self.extension) or str(self.file_path).endswith('_C'+ self.extension):
            write_ply_file(self.mesh_file, str(self.file_path).replace(self.extension, ".ply"))
        elif str(self.file_path).endswith('_rg.ply') or str(self.file_path).endswith('_C.ply'):
            write_ply_file(self.mesh_file, str(self.file_path))
        else:
            write_ply_file(self.mesh_file, self.file_path.with_name(self.file_path.stem+'_rg.ply'))
            self.file_path = self.file_path.with_name(self.file_path.stem+'_rg.ply')

        print(trans_y)

    def cranial_cut(self, initial_clip = False, resample = False):
        if initial_clip == True:
            clip = -20
        else:
            clip = 0

        template_mesh = GuiMethods.call_template(ICV_scaling=self.mesh_file.volume/2339070.752133594)
        template_mesh.points *= 1.2

        self.mesh_file.clip_box(template_mesh.bounds, invert=False)
        self.mesh_file.clip(normal=[0, 0.6, 1], origin=[0, -50, -60], invert=False)
        self.mesh_file = self.mesh_file.clip('z', origin=[0, 0, -21], invert=False)

        if str(self.file_path.stem).endswith('_C'):
            pass
        else:
            self.file_path = self.file_path.with_name(self.file_path.stem + '_C.ply')
        write_ply_file(self.mesh_file, self.file_path)


        GuiMethods.repairsample(self.file_path, n_vertices=20000, repair=True)

        self.mesh_file = pv.read(self.file_path)
        write_ply_file(self.mesh_file.clip('z', origin=[0, 0, clip], invert=False), self.file_path)

        GuiMethods.repairsample(self.file_path, n_vertices=10000, repair=False)

        self.mesh_file = pv.read(self.file_path)
        self.plotter.clear()

        self.plotter.add_mesh(self.mesh_file, color=self.mesh_color, show_edges=True)
        write_ply_file(self.mesh_file, self.file_path)


    # Craniometrics tab
    def craniometrics(self, slice_only = False):
        if slice_only==True:
            self.plotter.clear()

        metrics = CranioMetrics(self.file_path)
        metrics.extract_dimensions(metrics.slice_height)
        metrics.plot_craniometrics(self.plotter)


    # View tab
    def screenshot(self):
        try:
            screenshot_folder = Path(asksaveasfilename(title="Select file to open",
                                             filetypes=(("Screenshot", "*.png"),
                                                        ("all files", "*.*"))))
            self.plotter.screenshot(screenshot_folder)
        except:
            pass









