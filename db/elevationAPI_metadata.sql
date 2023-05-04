drop table if exists elevation_api_metadata;

create table elevation_api_metadata (
    region text not null,
    tileset text not null,
    a float not null,
    b float not null,
    c float not null,
    d float not null,
    e float not null,
    f float not null,
    bounds geometry(Polygon, 3006) not null,
    primary key (region, tileset)
);

create index geog_idx on metadata using gist (bounds);