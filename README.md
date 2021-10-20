# CraniumPy
CraniumPy is a simple tool that can be used to register 3D meshes for cranial analysis. In its current state, a raw 3D mesh (.ply, .obj, .stl) can be imported and visualized. Three anatomical landmarks were carefully selected (Nasion, LH tragus, RH tragus) and used for registration based on an average normal template (https://dined3d.io.tudelft.nl/en/mannequin/tool). 
Based on a single transverse slice (at max head depth), cephalometric measurements are automatically extracted and plotted on the 3D model. These measurements include:
- head depth
- breadth
- cephalic index
- head circumference
- intracranial volume approximation

## Installation and usage
Project is created with:
* Python version: 3.9

To run this project:
1. Create and/or load a virtual environment (optional) 
```
conda create -n yourenvname python=3.9
conda activate yourenvname
```
2. Clone repository
```
git clone https://github.com/T-AbdelAlim/CraniumPy.git
cd CraniumPy
```
4. Install requirements
```
pip install -r requirements.txt
```

5. Run tool
```
Python main.py
```

5. To get started check out the documentation in  ```/resources/documentation.pdf```

![Reconstruction](resources/CraniumPy_info.png)
