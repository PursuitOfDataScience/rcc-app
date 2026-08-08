URL: https://youzhi.netlify.app/post/2021-11-11-franchise/franchise/
Title: Media Franchise Data Visualization
Date: 2021-11-11
---

This blog post will analyze franchise revenue, and the data is from TidyTuesday Data Science online learning community. You can get the data from this [link](https://github.com/rfordatascience/tidytuesday/tree/master/data/2019/2019-07-02).

```r
library(tidyverse)
library(tidytext)
library(scales)
```

```r
media <- read_csv("https://raw.githubusercontent.com/rfordatascience/tidytuesday/master/data/2019/2019-07-02/media_franchises.csv") %>%
 mutate(original_media = str_to_title(original_media),
 revenue_category = str_to_title(revenue_category))

media
```

```
## # A tibble: 321 x 7
## franchise revenue_category revenue year_created original_media creators
## <chr> <chr> <dbl> <dbl> <chr> <chr>
## 1 A Song of I~ Book Sales 0.9 1996 Novel George R.~
## 2 A Song of I~ Box Office 0.001 1996 Novel George R.~
## 3 A Song of I~ Home Video/Enter~ 0.28 1996 Novel George R.~
## 4 A Song of I~ Tv 4 1996 Novel George R.~
## 5 A Song of I~ Video Games/Games 0.132 1996 Novel George R.~
## 6 Aladdin Box Office 0.76 1992 Animated Film Walt Disn~
## 7 Aladdin Home Video/Enter~ 1 1992 Animated Film Walt Disn~
## 8 Aladdin Merchandise, Lic~ 0.5 1992 Animated Film Walt Disn~
## 9 Aladdin Music 0.447 1992 Animated Film Walt Disn~
## 10 Aladdin Video Games/Games 2.2 1992 Animated Film Walt Disn~
## # ... with 311 more rows, and 1 more variable: owners <chr>
```

### Revenue for all franchises from various categories {#revenue-for-all-franchises-from-various-categories}

```r
media %>%
 mutate(original_media = fct_lump(original_media, n = 9),
 franchise = fct_reorder(franchise, revenue, sum, na.rm = T),
 original_media = fct_reorder(original_media, -revenue, sum)) %>%
 ggplot(aes(revenue, franchise, fill = revenue_category)) +
 geom_col() +
 facet_wrap(~original_media, scales = "free_y") +
 scale_x_continuous(labels = dollar) +
 labs(x = "revenue (in billions)",
 fill = "revenue category",
 title = "Revenue of All Franchises") +
 theme(legend.position = c(0.7, 0.15))
```

### Total revenue for the top franchises {#total-revenue-for-the-top-franchises}

```r
media %>%
 group_by(franchise) %>%
 mutate(total_revenue = sum(revenue, na.rm = T)) %>%
 ungroup() %>%
 arrange(desc(total_revenue)) %>%
 head(150) %>%
 mutate(franchise = paste0(franchise, " (", year_created, ")"),
 franchise = fct_reorder(franchise, revenue, sum)
 ) %>%
 ggplot(aes(revenue, franchise)) +
 geom_col(aes(fill = revenue_category)) +
 geom_text(aes(x = total_revenue,
 y = franchise,
 label = paste0(round(total_revenue), "B")), hjust = 0, check_overlap = T,
 color = "grey40") +
 scale_x_continuous(labels = dollar) +
 labs(x = "revenue (billions)",
 fill = "original media",
 title = "Total Revenue of the Top Franchises")
```

### Top owners’s revenue from multiple categories {#top-ownerss-revenue-from-multiple-categories}

```r
media %>%
 mutate(owners = str_remove(owners, " \\(.+"),
 owners = str_replace(owners, " ", " ")) %>%
 mutate(owners = fct_lump(owners, n = 8)) %>%
 filter(owners != "Other") %>%
 group_by(revenue_category, owners) %>%
 summarize(total_revenue = sum(revenue)) %>%
 ungroup() %>%
 mutate(owners = fct_reorder(owners, -total_revenue, sum)) %>%
 ggplot(aes(owners, revenue_category, fill = total_revenue)) +
 geom_tile() +
 scale_fill_gradient2(low = "red",
 high = "green",
 mid = "pink",
 midpoint = 20,
 label = dollar) +
 theme(panel.grid = element_blank(),
 axis.text.x = element_text(angle = 90)) +
 labs(y = "revenue category",
 fill = "revenue",
 title = "Revenue of Top 8 Owners from Various Categories")
```

### The relation between original media and revenue category {#the-relation-between-original-media-and-revenue-category}

```r
media %>%
 group_by(original_media) %>%
 mutate(total_revenue = sum(revenue)) %>%
 filter(total_revenue > 20) %>%
 ungroup() %>%
 group_by(original_media, revenue_category) %>%
 summarize(revenue = sum(revenue)) %>%
 ungroup() %>%
 mutate(revenue_category = reorder_within(revenue_category, revenue, original_media),
 original_media = fct_reorder(original_media, -revenue, sum)) %>%
 ggplot(aes(revenue, revenue_category, fill = revenue_category)) +
 geom_col(show.legend = F) +
 facet_wrap(~original_media, scales = "free_y") +
 scale_y_reordered() +
 scale_x_continuous(labels = dollar) +
 labs(y = "revenue category",
 title = "Where does original media make revenue?")
```

### Year V.S. revenue {#year-v.s.-revenue}

```r
media %>%
 group_by(year_created, franchise) %>%
 mutate(total_revenue = sum(revenue)) %>%
 distinct(franchise, .keep_all = T) %>%
 ungroup() %>%
 ggplot(aes(year_created, total_revenue, color = franchise)) +
 geom_point() +
 geom_text(aes(label = franchise), vjust = 1, hjust = 1, check_overlap = T) +
 expand_limits(x = 1920) +
 scale_y_continuous(labels = dollar) +
 theme(legend.position = "none",
 panel.grid = element_blank()) +
 labs(x = "year created",
 y = "revenue (in billions)",
 title = "Franchise Total Revenue and Year Created")
```
