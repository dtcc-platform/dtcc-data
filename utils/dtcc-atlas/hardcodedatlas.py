import json

width = 2500
height = 2500
atlas = {}

for i in range(100):
    x_coord = {}
    for j in range(100):
        y_coord = {}
        y_coord["width"] = width
        y_coord["height"] = height
        y_coord["filename"] = "{i},{j}".format(i = i,j =j)
        x_coord[j*height] = y_coord  
    atlas[i*width] = x_coord
    
        


with open('tester.json', 'w') as json_file:
    json.dump(atlas, json_file, indent=4)