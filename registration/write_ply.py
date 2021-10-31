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