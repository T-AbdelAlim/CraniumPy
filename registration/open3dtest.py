from pyvistaqt import BackgroundPlotter
import pyvista as pv
import numpy as np
import matplotlib.pyplot as plt
import os

main_dir = "/home/tareq/Notebooks_AAT/EMC_research/ICV_CT_correlation/Meshes_CT/at_CT_date/"

# % DATA
plotter = BackgroundPlotter()
clean_mesh = pv.read("/home/tareq/Notebooks_AAT/EMC_research/ICV_CT_correlation/Meshes_CT/at_CT_date/603-13122010/101217114915/101217114915_rg_C2.stl")
data_mesh = pv.read("/home/tareq/Notebooks_AAT/EMC_research/ICV_CT_correlation/Meshes_CT/at_CT_date/603-13122010/101217114915/101217114915_rg_C.stl")
imgdir = "/home/tareq/Notebooks_AAT/EMC_research/ICV_CT_correlation/Meshes_CT/images/"
for subdir, dirs, files in os.walk(main_dir):
    for file in files:
        if file.endswith("rg_C.stl"):
            file2 = file.split('.')[0]+'2.stl'

            clean_mesh = pv.read(subdir+'/'+file2)
            data_mesh = pv.read(subdir+'/'+file)

            # clean_list_y = []
            # clean_list_z = []
            # y_clean = clean_mesh.slice_along_axis(n=20, axis='y')
            # z_clean = clean_mesh.slice_along_axis(n=20, axis='z')
            # [clean_list_y.append(cy.delaunay_2d().area) for cy in y_clean]
            # [clean_list_z.append(cz.delaunay_2d().area) for cz in z_clean]

            raw_list_y = []
            raw_list_z = []
            y_raw = data_mesh.slice_along_axis(n=50, axis='y')
            z_raw = data_mesh.slice_along_axis(n=50, axis='z')
            # [raw_list_y.append(ry.delaunay_2d().area) for ry in y_raw]
            [raw_list_z.append(rz.delaunay_2d().area) for rz in z_raw]
            count = 0
            for idx, area in enumerate(raw_list_z[-5::]):
                if (raw_list_z[idx-1] - area) < 0:
                    count +=1
                    if count == 1:
                        print(idx, raw_list_z[idx-1] - area)
                        slice = 30-5 + idx

                        plotter.add_mesh(data_mesh)
                        plotter.add_mesh(z_raw[slice-1], color = 'red')
                        plotter.screenshot(imgdir+ file.split('.')[0]+'screen')
                        plotter.clear()
                        break
            # plt.plot(clean_list_z, color='blue')
            plt.plot(raw_list_z, color='red')
            plt.title(subdir.split('/')[-2])
            plt.show()

# plotter = BackgroundPlotter()
# m = pv.read("/home/tareq/Notebooks_AAT/EMC_research/ICV_CT_correlation/Meshes_CT/at_CT_date/2180-23052014/140523120120")
# plotter.add_mesh(m)
# plotter.add_mesh(m.slice(normal=[0, 0, 1], origin=[0, 0, 1]), color = 'red')