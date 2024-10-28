"""
Created on Mon Aug 2, 2021
"""

def write_ply_file(mesh, savepath):
    points = mesh.points
    faces = mesh.faces
    numVertices = mesh.n_points
    numFaces = mesh.n_faces
    faces = faces.reshape((numFaces, 4))
    with open(savepath, 'w+') as fileOut:
        # Writes ply header
        fileOut.write("ply\n")
        fileOut.write("format ascii 1.0\n")
        fileOut.write("comment VCGLIB generated\n")
        fileOut.write("element vertex " + str(numVertices) + "\n")
        fileOut.write("property float x\n")
        fileOut.write("property float y\n")
        fileOut.write("property float z\n")

        fileOut.write("element face " + str(numFaces) + "\n")
        fileOut.write("property list uchar int vertex_indices\n")
        fileOut.write("end_header\n")

        for i in range(numVertices):
            # writes "x y z" of current vertex
            fileOut.write(str(points[i,0]) + " " + str(points[i,1]) + " " + str(points[i,2]) + "255\n")

        # Writes faces
        for f in faces:
            #print(f)
            # WARNING: Subtracts 1 to vertex ID because PLY indices start at 0 and OBJ at 1
            fileOut.write("3 " + str(f[1]) + " " + str(f[2]) + " " + str(f[3]) + "\n")

import numpy as np


def write_ply_file2(mesh, savepath):
    points = mesh.points
    faces = mesh.faces
    numVertices = mesh.n_points
    numFaces = mesh.n_faces

    faces_list = []
    if isinstance(faces, np.ndarray) and faces.ndim == 1:
        i = 0
        while i < len(faces):
            if faces[i] == 3:  # Triangle face
                if i + 4 <= len(faces):
                    faces_list.append([3, faces[i + 1], faces[i + 2], faces[i + 3]])
                    i += 4
                else:
                    raise ValueError("Incomplete triangle face definition encountered in faces array.")
            elif faces[i] == 4:  # Quad face
                if i + 5 <= len(faces):
                    faces_list.append([4, faces[i + 1], faces[i + 2], faces[i + 3], faces[i + 4]])
                    i += 5
                else:
                    raise ValueError("Incomplete quad face definition encountered in faces array.")
            else:
                raise ValueError(f"Unsupported face format with identifier {faces[i]} at index {i}")
                i += 1
    else:
        raise ValueError("Faces data type or dimensions are not supported")

    faces_array = np.array(faces_list)

    with open(savepath, 'w+') as fileOut:
        # Writes ply header
        fileOut.write("ply\n")
        fileOut.write("format ascii 1.0\n")
        fileOut.write("comment VCGLIB generated\n")
        fileOut.write("element vertex " + str(numVertices) + "\n")
        fileOut.write("property float x\n")
        fileOut.write("property float y\n")
        fileOut.write("property float z\n")

        fileOut.write("element face " + str(len(faces_array)) + "\n")
        fileOut.write("property list uchar int vertex_indices\n")
        fileOut.write("end_header\n")

        for i in range(numVertices):
            # writes "x y z" of current vertex
            fileOut.write(f"{points[i, 0]} {points[i, 1]} {points[i, 2]}\n")

        # Writes faces
        for face in faces_array:
            if face[0] == 3:
                # Triangle face
                fileOut.write(f"3 {face[1]} {face[2]} {face[3]}\n")
            elif face[0] == 4:
                # Quad face
                fileOut.write(f"4 {face[1]} {face[2]} {face[3]} {face[4]}\n")


if __name__ == '__main__':
    import pyvista as pv
    import pyacvd
    import os

    # Directory containing the .ply files
    directory = r"C:\Users\Tareq\Documents\EMC\data_3d\FaceBase 3D data\FB-VWP\Weinberg\Images"

    # Loop through each file in the directory
    for filename in os.listdir(directory):
        if filename.endswith('.obj'):
            # Define the save path with _RS.ply suffix
            savepath = os.path.join(directory, filename.replace('.obj', '_RS.ply'))

            # Check if the _RS.ply file already exists
            if not os.path.exists(savepath):
                try:
                    # Load the mesh
                    filepath = os.path.join(directory, filename)
                    m = pv.read(filepath)

                    # Perform the clustering and remeshing
                    clus = pyacvd.Clustering(m)
                    clus.subdivide(3)
                    clus.cluster(len(m.points))
                    remesh = clus.create_mesh()

                    # Save the remeshed file
                    remesh.save(savepath)
                    print(f"Saved remeshed file: {savepath}")
                except ValueError:
                    print(f"Value Error: {savepath}")
            else:
                print(f"File already exists: {savepath}")