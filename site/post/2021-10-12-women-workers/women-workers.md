URL: https://youzhi.netlify.app/post/2021-10-12-women-workers/women-workers/
Title: Women in the Workforce Data Visualization
Date: 2021-10-12
---

The three datasets this post analyzes come from [TidyTuesday](https://github.com/rfordatascience/tidytuesday/tree/master/data/2019/2019-03-05).

```r
library(tidyverse)
library(scales)
library(tidytext)
```

```r
jobs_gender <- read_csv("https://raw.githubusercontent.com/rfordatascience/tidytuesday/master/data/2019/2019-03-05/jobs_gender.csv")
earnings_female <- read_csv("https://raw.githubusercontent.com/rfordatascience/tidytuesday/master/data/2019/2019-03-05/earnings_female.csv")
employed_gender <- read_csv("https://raw.githubusercontent.com/rfordatascience/tidytuesday/master/data/2019/2019-03-05/employed_gender.csv")
```

### Female salary percent of male salary {#female-salary-percent-of-male-salary}

```r
earnings_female %>%
 mutate(group = str_replace(group, " years", "")) %>%
 mutate(group = str_remove(group, ", .+"),
 group = fct_reorder(group, -percent, sum)) %>%
 #filter(group != "Total") %>%
 ggplot(aes(Year, percent, color = group)) +
 geom_point() +
 geom_line(size = 1) +
 scale_y_continuous(labels = percent_format(scale = 1)) +
 scale_x_continuous(breaks = seq(1980, 2010, 5)) +
 labs(x = NULL,
 y = "Female salary percent of male salary",
 title = "Female Salary Percent of Male Salary among Various Age Groups",
 subtitle = "Total group refers to 16 years and older")
```

### Working Status among Male and Female {#working-status-among-male-and-female}

```r
employed_gender %>%
 pivot_longer(-year, names_to = "work_type", values_to = "percent") %>%
 mutate(work_type = str_replace_all(work_type, "_", " "),
 work_type = fct_reorder(work_type, -percent, sum)) %>%
 ggplot(aes(year, percent, color = work_type)) +
 geom_point() +
 geom_line(size = 1) +
 scale_y_continuous(labels = percent_format(scale = 1)) +
 scale_x_continuous(breaks = seq(1965, 2020, 5)) +
 labs(x = NULL,
 y = "Percent of ",
 title = "Percentage of People of Working Full time or Part Time",
 subtitle = "total means total employed people working either full time or part time")
```

### Minor category female percentage and wage percent of male {#minor-category-female-percentage-and-wage-percent-of-male}

```r
jobs_gender %>%
 pivot_longer(cols = contains("percent"), names_to = "type", values_to = "percent") %>%
 group_by(minor_category, type, year) %>%
 summarize(avg_percent = mean(percent, na.rm = T)) %>%
 ungroup() %>%
 mutate(minor_category = fct_reorder(minor_category, -avg_percent, sum),
 type = str_replace_all(type, "_", " ")) %>%
 ggplot(aes(avg_percent, minor_category, fill = type)) +
 geom_col(position = "dodge") +
 scale_x_continuous(labels = percent_format(scale = 1), expand = c(0,1)) +
 theme(strip.text = element_text(size = 15, face = "bold")) +
 labs(x = "",
 y = "minor category",
 fill = NULL,
 title = "Minor Category Average Female Percentage and the Respective Wage Percent of Male") +
 expand_limits(x = 100) +
 facet_wrap(~year)
```

```r
jobs_gender %>%
 group_by(year) %>%
 slice_max(total_earnings, n = 10) %>%
 ungroup() %>%
 mutate(occupation = reorder_within(occupation, total_earnings, year)) %>%
 ggplot(aes(total_earnings, occupation, fill = major_category)) +
 geom_col() +
 theme(strip.text = element_text(size = 15, face = "bold"),
 axis.title = element_text(size = 15),
 axis.text.y = element_text(size = 10),
 plot.title = element_text(size = 18)) +
 facet_wrap(~year, scales = "free") +
 scale_y_reordered() +
 scale_x_continuous(labels = dollar)+
 labs(x = "median total earnings",
 y = NULL,
 fill = "major category",
 title = "Top 10 Total Median Earning Occupation from 2013 to 2016")
```

```r
jobs_gender %>%
 group_by(year, major_category, minor_category) %>%
 summarize_at(vars(contains("workers")), sum) %>%
 ungroup() %>%
 inner_join(
 jobs_gender %>%
 group_by(year, major_category, minor_category) %>%
 summarize(avg_percent = mean(wage_percent_of_male, na.rm = T)/100),
 by = c("year", "major_category", "minor_category")
 ) %>%
 mutate(minor_category = reorder_within(minor_category, workers_female, year)) %>%
 ggplot(aes(total_workers, minor_category, color = major_category)) +
 geom_pointrange(aes(x = workers_female, y = minor_category,
 xmin = 0, xmax = total_workers,
 size = avg_percent)) +
 facet_wrap(~year, scales = "free_y") +
 scale_y_reordered() +
 scale_size_continuous(range = c(0.1,1), labels = percent) +
 scale_x_continuous(labels = comma) +
 labs(
 x = "# of workers",
 y = "minor category",
 color = "major category",
 size = "average percent of male wage",
 title = "Category-wise # of Workers",
 subtitle = "The length of each line represents the total # of workers in each category\nThe position of dot refers to # of female workers\nThe size of dot refers to the average percent of male wage"
 ) +
 theme(
 strip.text = element_text(size = 15, face = "bold"),
 axis.title = element_text(size = 15),
 plot.title = element_text(size = 18)
 )
```
