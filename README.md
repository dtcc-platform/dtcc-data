# DTCC Data

DTCC Data provides an initial datalake scraped of LM's repository and an accompanying API for DTCC Platform.

This project is part of the
[Digital Twin Platform (DTCC Platform)](https://github.com/dtcc-platform/)
developed at the
[Digital Twin Cities Centre](https://dtcc.chalmers.se/)
supported by Sweden’s Innovation Agency Vinnova under Grant No. 2019-421 00041.

## Documentation

This project is documented as part of the
[DTCC Platform Documentation](https://platform.dtcc.chalmers.se/).

For the merged data server deployment and usage, see `README-server.md`.

## Datasets and Modular Atlas

You can serve multiple GeoPackage datasets (each with its own tiles and atlas) using the dataset-aware workflow:

- Create/register a dataset: run `src/create-atlas-gpkg-modular.py <dataset>` to build tiles and update `src/dtcc_data/gpkg_datasets.json`.
- Run the server and query dataset endpoints (documented in `README-server.md`).
- Client wrappers include `download_footprints_dataset(...)` under `dtcc_data.wrapper`.


## Authors (in order of appearance)

* [Dag Wästerberg](https://chalmersindustriteknik.se/sv/medarbetare/dag-wastberg/)
* [Anders Logg](http://anders.logg.org)
* [Vasilis Naserentin](https://www.chalmers.se/en/persons/vasnas/)
* [Themis Arvanitis](https://dtcc.chalmers.se)


## License

This project is licensed under the
[MIT license](https://opensource.org/licenses/MIT).

Copyright is held by the individual authors as listed at the top of
each source file.

## Community guidelines

Comments, contributions, and questions are welcome. Please engage with
us through Issues, Pull Requests, and Discussions on our GitHub page.
