package com.example.app.services.catalog.controller;

import com.example.app.common.constant.Category;
import com.example.app.common.constant.FilmRating;
import com.example.app.services.auth.domain.vo.UserRole;
import com.example.app.services.catalog.assembler.ActorDetailsRepresentationModelAssembler;
import com.example.app.services.catalog.assembler.ActorRepresentationModelAssembler;
import com.example.app.services.catalog.assembler.FilmDetailsRepresentationModelAssembler;
import com.example.app.services.catalog.assembler.FilmRepresentationModelAssembler;
import com.example.app.services.catalog.domain.dto.ActorDto;
import com.example.app.services.catalog.domain.dto.FilmDetailsDto;
import com.example.app.services.catalog.domain.dto.FilmDto;
import com.example.app.services.catalog.service.FilmService;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.data.web.PageableDefault;
import org.springframework.hateoas.CollectionModel;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.annotation.Secured;
import org.springframework.web.bind.annotation.*;

import java.time.Year;

import static org.springframework.hateoas.server.mvc.WebMvcLinkBuilder.linkTo;
import static org.springframework.hateoas.server.mvc.WebMvcLinkBuilder.methodOn;

@RestController
@RequestMapping(value = "/films")
@RequiredArgsConstructor
public class FilmController {
    private final FilmService filmService;
    private final FilmRepresentationModelAssembler filmAssembler;
    private final FilmDetailsRepresentationModelAssembler filmDetailsAssembler;
    private final ActorRepresentationModelAssembler actorAssembler;
    private final ActorDetailsRepresentationModelAssembler actorDetailsAssembler;

    @GetMapping(path = "")
    @Secured(UserRole.Constants.ROLE_READ)
    public ResponseEntity<CollectionModel<FilmDto.FilmResponse>> getFilmList(
            @RequestParam(required = false) String category,
            @RequestParam(required = false) String releaseYear,
            @RequestParam(required = false) String rating,
            @PageableDefault(size = 10, page = 0, direction = Sort.Direction.ASC) Pageable pageable) {
        final var condition = FilmDto.FilterOption.builder()
                .category(category == null ? null : Category.CATEGORY_LOWER_MAP.get(category.toLowerCase()))
                .releaseYear(releaseYear == null ? null : Year.parse(releaseYear))
                .rating(rating == null ? null : FilmRating.valueOf(rating))
                .build();
        return ResponseEntity.ok(filmAssembler.toCollectionModel(
                filmService.getFilmList(condition, pageable)));
    }

    @PostMapping(path = "")
    @Secured(UserRole.Constants.ROLE_MANAGE)
    public ResponseEntity<Void> addFilm(@RequestBody FilmDto.FilmRequest model) {
        final var result = filmService.addFilm(model);
        return ResponseEntity.created(linkTo(methodOn(FilmController.class)
                .getFilm(result.getFilmId())).toUri()).build();
    }

    @GetMapping(path = "/{filmId}")
    @Secured(UserRole.Constants.ROLE_READ)
    public ResponseEntity<FilmDto.FilmResponse> getFilm(@PathVariable Integer filmId) {
        return filmService.getFilm(filmId)
                .map(filmAssembler::toModel)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @PutMapping(path = "/{filmId}")
    @Secured(UserRole.Constants.ROLE_MANAGE)
    public ResponseEntity<Void> updateFilm(@PathVariable Integer filmId,
                                           @RequestBody FilmDto.FilmRequest model) {
        final var result = filmService.updateFilm(filmId, model);
        return ResponseEntity.ok().build();
    }

    @DeleteMapping(path = "/{filmId}")
    @Secured(UserRole.Constants.ROLE_MANAGE)
    public ResponseEntity<Void> deleteFilm(@PathVariable Integer filmId) {
        filmService.deleteFilm(filmId);
        return ResponseEntity.noContent().build();
    }

    @GetMapping(path = "/{filmId}/actors")
    @Secured(UserRole.Constants.ROLE_READ)
    public ResponseEntity<CollectionModel<ActorDto.ActorResponse>> getFilmActorList(
            @PathVariable Integer filmId,
            @PageableDefault(size = 10, page = 0, direction = Sort.Direction.ASC) Pageable pageable) {
        return ResponseEntity.ok(actorAssembler.toCollectionModel(
                filmService.getFilmActorList(filmId, pageable)));
    }

    @GetMapping(path = "/{filmId}/actors/{actorId}")
    @Secured(UserRole.Constants.ROLE_READ)
    public ResponseEntity<ActorDto.ActorResponse> getFilmActor(@PathVariable Integer filmId,
                                                               @PathVariable Integer actorId) {
        return filmService.getFilmActor(filmId, actorId)
                .map(actorAssembler::toModel)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @GetMapping(path = "/{filmId}/details")
    @Secured(UserRole.Constants.ROLE_READ)
    public ResponseEntity<FilmDetailsDto.FilmDetailsResponse> getFilmDetails(@PathVariable Integer filmId) {
        return filmService.getFilmDetails(filmId)
                .map(filmDetailsAssembler::toModel)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }
}
