import numpy as np
from prototype import findFiles
from shapely.geometry import box

bounds = box(0, 0, 25000, 25000)
server_files = findFiles("atlas.json", bounds)
local_files = findFiles("tester.json", bounds)

def filesToSend(local, server):
    local = np.array(local)
    server = np.array(server)
    dif1 = np.setdiff1d(local, server)
    dif2 = np.setdiff1d(server, local)
    
    temp3 = np.concatenate((dif1, dif2))
    return temp3

print(filesToSend(local_files, server_files))