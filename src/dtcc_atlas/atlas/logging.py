# Copyright(C) 2023 Anders Logg
# Licensed under the MIT License

from dtcc_common import init_logging

debug, info, warning, error, critical = init_logging("dtcc-atlas")


def file_diff_info(local_files: list[str], server_files: list[str], debug: bool = False)->list[str]:
  """Compares the local files with the server files, 
    prints how many files are stored locally, how many on the server, 
    and which files from the server are missing locally.

    Args:
        local_files (list): List of filenames stored locally.
        server_files (list): List of filenames stored on the server.
    """
  
  # Files missing from local storage
  missing_files = [file for file in server_files if file not in local_files]
    
  # Print the results
  info(f"Number of files stored locally: {len(local_files)}")
  info(f"Number of files stored on the server: {len(server_files)}")
  info(f"Number of files missing locally: {len(missing_files)}")
    
  if missing_files:
    info("Files missing locally:")
    for file in missing_files:
      info(f"- {file}")
  else:
    info("All server files are available locally.")

  if debug:
    sorted_local_files = sorted(local_files)
    sorted_server_files = sorted(server_files)
    print_file_lists_side_by_side(sorted_local_files,sorted_server_files)

  return missing_files

def print_file_lists_side_by_side(local_files,server_files):
  """Prints local and server files side by side."""
  # Determine the maximum length of the two lists
  max_length = max(len(local_files), len(server_files))

  # Print header
  print(f"{'Local Files':<30} {'Server Files':<30}")
  print('-' * 60)  # Separator line

  # Iterate over both lists, filling with empty strings if one is shorter
  for i in range(max_length):
      local_file = local_files[i] if i < len(local_files) else ""
      server_file = server_files[i] if i < len(server_files) else ""
      print(f"{local_file:<30} {server_file:<30}")