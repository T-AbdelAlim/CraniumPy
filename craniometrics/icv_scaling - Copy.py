from pyvistaqt import BackgroundPlotter
import pyvista as pv
import numpy as np


plotter = BackgroundPlotter()
template_mesh = pv.read("/data/template/clipped_template_ntplane.stl")
data_mesh = pv.read("/data/patient_folder/746-06102006/061006124733/061006124733_rg_C.stl")
data_mesh_ref = pv.read("/data/patient_folder/603-13122010/101217114915/101217114915_rg_CR.stl")

# ### calculate mesh volumes (1/1000*mm^3 --> cm^3)
# vol_T = data_mesh_ref.volume/1000 # template volume
# vol_M = data_mesh.volume/1000 # mesh volume
#
# ### resizing the mesh such that its volume == volume of the template mesh
# data_mesh_ref.points *= (vol_M/vol_T)**(1/3)
#
# AX_templ = data_mesh_ref.center_of_mass()
# AX_slice = data_mesh.center_of_mass()
# AX_diff = (AX_templ[1] - AX_slice[1])  # /2
#
# data_mesh_ref.translate([0,-AX_diff,0])

### Add original mesh and template
plotter.add_mesh(data_mesh, color='white', show_edges=True, opacity=0.1)
plotter.add_mesh(data_mesh_ref, color='red', show_edges=True, opacity=0.1)


# ### check if V_mesh == V_template
# print('volume difference = {} cm^3'.format(round((template_mesh.volume/1000) - vol_M)))


# ### Mesh slices
# n_slices = 30
# axes = ['x', 'y', 'z']
# for axis in axes:
#     ### slices Template
#     SAG_templ_T = template_mesh.slice_along_axis(n=n_slices, axis=axis)
#     plotter.add_mesh(SAG_templ_T, color='red')
#     center_slice_T = SAG_templ_T[int(n_slices/2)]
#     plotter.add_mesh(center_slice_T, color='red')
#
#     ### slices Mesh
#     SAG_templ_M = data_mesh.slice_along_axis(n=n_slices, axis=axis)
#     plotter.add_mesh(SAG_templ_M, color='yellow')
#     center_slice_M = SAG_templ_M[int(n_slices/2)]
#     plotter.add_mesh(center_slice_M, color='yellow')


# data_mesh = pv.read("/home/tareq/PycharmProjects/pythonProject/pycranium/data/100223132826.ply")
#
# data_mesh.translate(200)
# cranium = data_mesh.clip('z', origin=[100, 200, 200], invert=False)
# color_arr = cranium.point_arrays['RGBA']
# plotter.show_grid()
# cranium.save("mesh.ply")
#
# new_mesh = pv.read("mesh.ply")
# new_mesh['color'] = color_arr
# plotter.add_mesh(new_mesh, scalars='color', rgba=True, show_edges=True)


# from scipy.spatial import KDTree
# tree = KDTree(data_mesh_ref.points)
# d, idx = tree.query(data_mesh.points )
# data_mesh["distances"] = d
# np.mean(d)
#
# plotter.add_mesh(data_mesh, scalars="distances", smooth_shading=True)
# plotter.add_mesh(data_mesh_ref, color=True, opacity=0.75, smooth_shading=True)
# plotter.show()

