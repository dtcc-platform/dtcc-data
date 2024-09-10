import json
import unittest
from unittest.mock import MagicMock, mock_open, patch
from dtcc_atlas.atlas import download_roadnetwork
from shapely import box

class testAtlas(unittest.TestCase):
        
    @patch('builtins.open', new_callable=mock_open, read_data='{}')
    @patch('requests.get')
    @patch('tarfile.open')
    @patch('os.listdir')
    @patch('os.rename')
    @patch('os.makedirs')
    @patch('shutil.rmtree')
    @patch('os.remove')
    def test_fetch_data(self, mock_remove, mock_rmtree, mock_makedirs, mock_rename, mock_listdir, mock_tarfile_open, mock_requests_get, mock_open):
        # Mocking the return values
        mock_requests_get.return_value.content = b'fake tar content'
        mock_listdir.return_value = ['file1', 'file2']
        
        # Mocking tarfile extraction
        mock_tar = MagicMock()
        mock_tarfile_open.return_value.__enter__.return_value = mock_tar

        # Running the function
        bbox = box(445646,7171055, 458746,7195055)
        download_roadnetwork(bbox)

        # Assert that we made a request to fetch missing data
        mock_requests_get.assert_called_once_with('http://129.16.69.36:54321/download-vl', stream=True, json={'filenames': ['tile_446646_7171055.gpkg', 'tile_446646_7181055.gpkg', 'tile_446646_7191055.gpkg', 'tile_456646_7171055.gpkg', 'tile_456646_7181055.gpkg', 'tile_456646_7191055.gpkg']})

        # Assert that files were extracted and renamed
        mock_tar.extractall.assert_called_once_with('new_files')


   
        
if __name__ == '__main__':
    unittest.main()
        