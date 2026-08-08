URL: https://youzhi.netlify.app/post/2022-04-04-broadband/broadband/
Title: Broadband Data Visualization with zipcodeR and tigris Used
Date: 2022-04-04
---

This blog post will analyze the broadband availability and usage situation across the U.S. per county. This is my first time using `zipcodeR` and `tigris` in a blog post, and this is also my first time making a U.S. map on county-level. Thanks [TidyTuesday](https://github.com/rfordatascience/tidytuesday/tree/master/data/2021/2021-05-11) for providing the datasets.

```r
library(tidyverse)
library(geofacet)
library(scales)
library(zipcodeR)
library(tigris)
library(sf)
theme_set(theme_bw())
```

```r
broadband <- read_csv('https://raw.githubusercontent.com/rfordatascience/tidytuesday/master/data/2021/2021-05-11/broadband.csv') %>%
 janitor::clean_names() %>%
 left_join(
 tibble(st = state.abb,
 state = state.name),
 by = "st"
 ) %>%
 rename(county = county_name,
 bb_avail = broadband_availability_per_fcc,
 bb_usage = broadband_usage) %>%
 mutate(county = str_remove(county, "\\s.+$"),
 across(bb_avail:bb_usage, as.numeric),
 county_id = sprintf("%05d", county_id)) %>%
 filter(!is.na(state))

bb_zip <- read_csv("https://raw.githubusercontent.com/rfordatascience/tidytuesday/master/data/2021/2021-05-11/broadband_zip.csv") %>%
 janitor::clean_names() %>%
 rename(county = county_name) %>%
 left_join(
 tibble(st = state.abb,
 state = state.name),
 by = "st"
 ) %>%
 mutate(postal_code = sprintf("%05d", postal_code))

broadband
```

```
## # A tibble: 3,142 x 6
## st county_id county bb_avail bb_usage state
## <chr> <chr> <chr> <dbl> <dbl> <chr>
## 1 AL 01001 Autauga 0.81 0.28 Alabama
## 2 AL 01003 Baldwin 0.88 0.3 Alabama
## 3 AL 01005 Barbour 0.59 0.18 Alabama
## 4 AL 01007 Bibb 0.29 0.07 Alabama
## 5 AL 01009 Blount 0.69 0.09 Alabama
## 6 AL 01011 Bullock 0.06 0.05 Alabama
## 7 AL 01013 Butler 0.78 0.11 Alabama
## 8 AL 01015 Calhoun 0.93 0.32 Alabama
## 9 AL 01017 Chambers 0.82 0.34 Alabama
## 10 AL 01019 Cherokee 0.99 0.1 Alabama
## # ... with 3,132 more rows
```

```r
county_map <- state.name %>%
 tibble(state = .) %>%
 mutate(state = str_to_lower(state)) %>%
 mutate(map_data = list(map_data("county", state))) %>%
 unnest(map_data) %>%
 select(-region) %>%
 rename(county = subregion) %>%
 mutate(across(c(state, county), str_to_title))

county_map
```

```
## # A tibble: 4,396,950 x 6
## state long lat group order county
## <chr> <dbl> <dbl> <dbl> <int> <chr>
## 1 Alabama -86.5 32.3 1 1 Autauga
## 2 Alabama -86.5 32.4 1 2 Autauga
## 3 Alabama -86.5 32.4 1 3 Autauga
## 4 Alabama -86.6 32.4 1 4 Autauga
## 5 Alabama -86.6 32.4 1 5 Autauga
## 6 Alabama -86.6 32.4 1 6 Autauga
## 7 Alabama -86.6 32.4 1 7 Autauga
## 8 Alabama -86.6 32.4 1 8 Autauga
## 9 Alabama -86.6 32.4 1 9 Autauga
## 10 Alabama -86.6 32.4 1 10 Autauga
## # ... with 4,396,940 more rows
```

Broadband usage and availability usage per state:

```r
broadband %>%
 ggplot(aes(bb_avail, bb_usage, color = st)) +
 geom_point(alpha = 0.3, size = 1, show.legend = F) +
 facet_geo(~st) +
 scale_x_continuous(labels = percent) +
 scale_y_continuous(labels = percent) +
 theme(axis.text.x = element_text(angle = 90),
 panel.grid = element_blank()) +
 labs(x = "broadband availability",
 y = "broadband usage",
 title = "Broadband Availability and Usage Per State Per County")
```

```r
broadband %>%
 rename(`Broadband Availability` = bb_avail,
 `Broadband Usage` = bb_usage) %>%
 pivot_longer(4:5, names_to = "metric") %>%
 ggplot(aes(value, state, fill = state, color = state)) +
 geom_boxplot(alpha = 0.4) +
 facet_wrap(~metric) +
 theme(legend.position = "none",
 panel.grid = element_blank()) +
 labs(x = NULL,
 y = NULL,
 title = "Broadband Availability and Usage Per State") +
 scale_x_continuous(labels = percent)
```

```r
county_map %>%
 inner_join(broadband %>%
 select(-st, -county_id),
 by = c("state", "county")) %>%
 ggplot(aes(long, lat, group = group)) +
 geom_polygon(aes(fill = bb_usage)) +
 coord_map() +
 theme_void() +
 scale_fill_gradient(high = "green",
 low = "red",
 labels = percent) +
 labs(fill = "broadband usage",
 title = "Broadband Usage per County")
```

```r
county_map %>%
 inner_join(broadband %>%
 select(-st, -county_id),
 by = c("state", "county")) %>%
 ggplot(aes(long, lat, group = group)) +
 geom_polygon(aes(fill = bb_avail)) +
 coord_map() +
 theme_void() +
 scale_fill_gradient(high = "green",
 low = "red",
 labels = percent) +
 labs(fill = "broadband availability",
 title = "Broadband Availability per County")
```

The percentage of broadband availability is generally larger than its of broadband usage across the U.S.

Broandband availability per county:

```r
counties_sf <- counties()
```

```r
counties_sf %>%
 inner_join(broadband %>%
 filter(!st %in% c("HI", "AK")),
 by = c("GEOID" = "county_id")) %>%
 st_simplify(dTolerance = .1) %>%
 ggplot() +
 geom_sf(aes(fill = bb_avail)) +
 ggthemes::theme_map() +
 coord_sf() +
 scale_fill_gradient2(
 high = "green",
 low = "red",
 mid = "pink",
 midpoint = 0.25,
 labels = percent
 ) +
 labs(fill = "broadband availability",
 title = "Broandband Availability per County")
```

Broandband usage per county:

```r
counties_sf %>%
 inner_join(broadband %>%
 filter(!st %in% c("HI", "AK")),
 by = c("GEOID" = "county_id")) %>%
 st_simplify(dTolerance = .1) %>%
 ggplot() +
 geom_sf(aes(fill = bb_usage)) +
 ggthemes::theme_map() +
 coord_sf() +
 scale_fill_gradient2(
 high = "green",
 low = "red",
 mid = "pink",
 midpoint = 0.25,
 labels = percent
 ) +
 labs(fill = "broadband usage",
 title = "Broandband Uage per County")
```
