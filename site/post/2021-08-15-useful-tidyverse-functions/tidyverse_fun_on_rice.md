URL: https://youzhi.netlify.app/post/2021-08-15-useful-tidyverse-functions/tidyverse_fun_on_rice/
Title: The Tidyverse Functions Less Known But Handy
Date: 2021-08-15
---

Recently, I came across the blog post by Emily Robinson titled Lesser Known Stars of the Tidyverse, and here is the [link](https://hookedondata.org/the-lesser-known-stars-of-the-tidyverse/). After reading through the blog, I indeed learned some “hidden” functions I had not been aware of, and knowing how to harness them in my everyday data science work would definitely make my life easier, as I encountered similar situations from time to time that had I known some of these “less known stars” I would process data more quickly. In this data science blog, I will use some of these functions mentioned in her blog on a rice classification dataset found on [Kaggle](https://www.kaggle.com/mssmartypants/rice-type-classification).

### Data Introduction {#data-introduction}

Since all of the functions are from `tidyverse` ecosystem. Let’s load it first and then load the rice dataset.

```r
library(tidyverse)
rice <- read_csv("riceClassification.csv")
head(rice)
```

```
## # A tibble: 6 x 12
## id Area MajorAxisLength MinorAxisLength Eccentricity ConvexArea
## <dbl> <dbl> <dbl> <dbl> <dbl> <dbl>
## 1 1 4537 92.2 64.0 0.720 4677
## 2 2 2872 74.7 51.4 0.726 3015
## 3 3 3048 76.3 52.0 0.731 3132
## 4 4 3073 77.0 51.9 0.739 3157
## 5 5 3693 85.1 56.4 0.749 3802
## 6 6 2990 77.4 51.0 0.753 3080
## # ... with 6 more variables: EquivDiameter <dbl>, Extent <dbl>,
## # Perimeter <dbl>, Roundness <dbl>, AspectRation <dbl>, Class <dbl>
```

```r
dim(rice)
```

```
## [1] 18185 12
```

### The 1st Function: summarize_at() {#the-1st-function-summarize_at}

This function is highly useful, as `group_by()` is something I use all the time whenever I do data visualization and analysis, and what goes with it is `summarize()`. What is not convenient about `summarize()` is that if we need to deal with a number of columns, inputting them one by one could be painful and repetitious. `summarize_at()` provides a perfect solution to type less. Let’s give it shot!

```r
# checking if any column has any missing values
rice %>%
 summarize_at(2:11, ~sum(is.na(.)))
```

```
## # A tibble: 1 x 10
## Area MajorAxisLength MinorAxisLength Eccentricity ConvexArea EquivDiameter
## <int> <int> <int> <int> <int> <int>
## 1 0 0 0 0 0 0
## # ... with 4 more variables: Extent <int>, Perimeter <int>, Roundness <int>,
## # AspectRation <int>
```

```r
# group by Class column and get the mean of each column respectively
rice %>%
 group_by(Class) %>%
 summarize_at(2:11, ~mean(.))
```

```
## # A tibble: 2 x 11
## Class Area MajorAxisLength MinorAxisLength Eccentricity ConvexArea
## <dbl> <dbl> <dbl> <dbl> <dbl> <dbl>
## 1 0 8359. 154. 70.0 0.889 8575.
## 2 1 5951. 150. 51.4 0.937 6118.
## # ... with 5 more variables: EquivDiameter <dbl>, Extent <dbl>,
## # Perimeter <dbl>, Roundness <dbl>, AspectRation <dbl>
```

```r
# instead of inputting the column numbers, typing column names would also be an option
rice %>%
 group_by(Class) %>%
 summarize_at(vars(Area:AspectRation), ~mean(.))
```

```
## # A tibble: 2 x 11
## Class Area MajorAxisLength MinorAxisLength Eccentricity ConvexArea
## <dbl> <dbl> <dbl> <dbl> <dbl> <dbl>
## 1 0 8359. 154. 70.0 0.889 8575.
## 2 1 5951. 150. 51.4 0.937 6118.
## # ... with 5 more variables: EquivDiameter <dbl>, Extent <dbl>,
## # Perimeter <dbl>, Roundness <dbl>, AspectRation <dbl>
```

The above code is essentially functional programming at the core, which might be a tad intimidating when getting exposed to it in the first place. We can use `purrr` package to loosely carry out the similar job as we did above.

```r
rice %>%
 purrr::map_df(~sum(is.na(.)))
```

```
## # A tibble: 1 x 12
## id Area MajorAxisLength MinorAxisLength Eccentricity ConvexArea
## <int> <int> <int> <int> <int> <int>
## 1 0 0 0 0 0 0
## # ... with 6 more variables: EquivDiameter <int>, Extent <int>,
## # Perimeter <int>, Roundness <int>, AspectRation <int>, Class <int>
```

```r
rice %>%
 purrr::map_df(~mean(.))
```

```
## # A tibble: 1 x 12
## id Area MajorAxisLength MinorAxisLength Eccentricity ConvexArea
## <dbl> <dbl> <dbl> <dbl> <dbl> <dbl>
## 1 9093 7036. 152. 59.8 0.915 7226.
## # ... with 6 more variables: EquivDiameter <dbl>, Extent <dbl>,
## # Perimeter <dbl>, Roundness <dbl>, AspectRation <dbl>, Class <dbl>
```

```r
rice %>%
 summarize_at(vars(Area:AspectRation), ~mean(.))
```

```
## # A tibble: 1 x 10
## Area MajorAxisLength MinorAxisLength Eccentricity ConvexArea EquivDiameter
## <dbl> <dbl> <dbl> <dbl> <dbl> <dbl>
## 1 7036. 152. 59.8 0.915 7226. 94.1
## # ... with 4 more variables: Extent <dbl>, Perimeter <dbl>, Roundness <dbl>,
## # AspectRation <dbl>
```

Why did I put “loosely” above? `map_df()` applies the dataset globally, yet `summarize_at()` offers users options to select columns. Therefore, `map_df()` is more like the function we will introduce now, which is `summarize_all()`.

### The 2nd Function: summarize_all() {#the-2nd-function-summarize_all}

The variation of `summarize_at()` is `summarize_all()`. Based on the Emily’s blog, the only difference between them is that `summarize_all()` applies every single column of the dataset without having any option of choosing specific columns based on user’s preferences.

```r
rice %>%
 summarize_all(~mean(.))
```

```
## # A tibble: 1 x 12
## id Area MajorAxisLength MinorAxisLength Eccentricity ConvexArea
## <dbl> <dbl> <dbl> <dbl> <dbl> <dbl>
## 1 9093 7036. 152. 59.8 0.915 7226.
## # ... with 6 more variables: EquivDiameter <dbl>, Extent <dbl>,
## # Perimeter <dbl>, Roundness <dbl>, AspectRation <dbl>, Class <dbl>
```

The output is identical as the output `rice %>% purrr::map_df(~mean(.))`, which is nice!

### The 3rd Function: skim() {#the-3rd-function-skim}

`skim()` is essentially giving users some traditional summary statistics of the dataset column-wise. Before reading this Emily’s very blog, I’d never used this function, but sometimes it would be useful to have such a summary out along with histograms!

```r
rice %>%
 select_if(is.numeric) %>%
 skimr::skim()
```

Table 1: Data summary | Name | Piped data

 | Number of rows | 18185

 | Number of columns | 12

 | _______________________ |

 | Column type frequency: |

 | numeric | 12

 | ________________________ |

 | Group variables | None

**Variable type: numeric**

 | skim_variable | n_missing | complete_rate | mean | sd | p0 | p25 | p50 | p75 | p100 | hist

 | id | 0 | 1 | 9093.00 | 5249.70 | 1.00 | 4547.00 | 9093.00 | 13639.00 | 18185.00 | ▇▇▇▇▇

 | Area | 0 | 1 | 7036.49 | 1467.20 | 2522.00 | 5962.00 | 6660.00 | 8423.00 | 10210.00 | ▁▂▇▃▃

 | MajorAxisLength | 0 | 1 | 151.68 | 12.38 | 74.13 | 145.68 | 153.88 | 160.06 | 183.21 | ▁▁▂▇▂

 | MinorAxisLength | 0 | 1 | 59.81 | 10.06 | 34.41 | 51.39 | 55.72 | 70.16 | 82.55 | ▁▇▃▆▂

 | Eccentricity | 0 | 1 | 0.92 | 0.03 | 0.68 | 0.89 | 0.92 | 0.94 | 0.97 | ▁▁▁▆▇

 | ConvexArea | 0 | 1 | 7225.82 | 1502.01 | 2579.00 | 6125.00 | 6843.00 | 8645.00 | 11008.00 | ▁▃▇▅▂

 | EquivDiameter | 0 | 1 | 94.13 | 9.91 | 56.67 | 87.13 | 92.09 | 103.56 | 114.02 | ▁▁▇▆▆

 | Extent | 0 | 1 | 0.62 | 0.10 | 0.38 | 0.54 | 0.60 | 0.70 | 0.89 | ▃▇▇▅▂

 | Perimeter | 0 | 1 | 351.61 | 29.50 | 197.01 | 333.99 | 353.09 | 373.00 | 508.51 | ▁▂▇▂▁

 | Roundness | 0 | 1 | 0.71 | 0.07 | 0.17 | 0.65 | 0.70 | 0.77 | 0.90 | ▁▁▁▇▅

 | AspectRation | 0 | 1 | 2.60 | 0.43 | 1.36 | 2.21 | 2.60 | 2.96 | 3.91 | ▁▇▅▆▁

 | Class | 0 | 1 | 0.55 | 0.50 | 0.00 | 0.00 | 1.00 | 1.00 | 1.00 | ▆▁▁▁▇

Staring the output above, what has intrigued me most would be the `hist` column where how datapoints are distributed across the entire dataset at each specific column is clearly visualized. I do think that `skim()` is a useful function when we would like to have an overview of dataset in the initial explorative analysis.

### Conclusion {#conclusion}

The three aforementioned functions are not well known but are highly useful. Of course, her blog also mentioned other functions that fall into this category as well, such as `forcats::fct_relevel`, `gather()` and `na_if()`. Just a simple note on `gather()` and `melt()` functions, now in my everyday work I have replaced both functions by `pivot_wider()` and `pivot_longer()`, which are rather handy to restructure the dataset. This is especially the case when using `ggplot()` to visualize the dataset. Also, `fct_relevel()` is rather handy when using it along with data visualization, and this is especially the case when using `geom_col()` to make a bar chart that columns are not very well ordered sequentially. Sometimes, the missing values presented in a dataset are not in the canonical `NA` form but other weird forms, and this is where `na_if()` function can be useful to transform the de facto missing values into the `NA`.

It is always a nice thing to practice and compare these functions in `tidyverse` ecosystem, and doing so would help us process datasets more efficient and more quickly, thus deepening the understanding of data science in general.
