package com.example.app.services.catalog.controller;

import com.example.app.common.constant.Category;
import com.example.app.common.constant.FilmRating;
import com.example.app.common.constant.HalRelation;
import com.example.app.services.auth.domain.vo.UserRole;
import com.example.app.services.catalog.assembler.ActorDetailsRepresentationModelAssembler;
import com.example.app.services.catalog.assembler.ActorRepresentationModelAssembler;
import com.example.app.services.catalog.assembler.FilmDetailsRepresentationModelAssembler;
import com.example.app.services.catalog.assembler.FilmRepresentationModelAssembler;
import com.example.app.services.catalog.domain.dto.ActorDetailsDto;
import com.example.app.services.catalog.domain.dto.ActorDto;
import com.example.app.services.catalog.domain.dto.FilmDetailsDto;
import com.example.app.services.catalog.domain.dto.FilmDto;
import com.example.app.services.catalog.service.ActorService;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.data.web.PageableDefault;
import org.springframework.hateoas.CollectionModel;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.annotation.Secured;
import org.springframework.web.bind.annotation.*;

import java.time.Year;
import java.util.Map;

import static org.springframework.hateoas.server.mvc.WebMvcLinkBuilder.linkTo;
import static org.springframework.hateoas.server.mvc.WebMvcLinkBuilder.methodOn;

@RestController
@RequestMapping(value = "/actors")
@RequiredArgsConstructor
public class ActorController {
    private final ActorService actorService;
    private final ActorRepresentationModelAssembler actorAssembler;
    private final ActorDetailsRepresentationModelAssembler actorDetailsAssembler;
    private final FilmRepresentationModelAssembler filmAssembler;
    private final FilmDetailsRepresentationModelAssembler filmDetailsAssembler;

    @GetMapping(path = "")
    @Secured(UserRole.Constants.ROLE_READ)
    public ResponseEntity<CollectionModel<ActorDto.ActorResponse>> getActorList(
            @PageableDefault(size = 10, page = 0, direction = Sort.Direction.ASC) Pageable pageable) {
        return ResponseEntity.ok(actorAssembler.toCollectionModel(
                actorService.getActorList(pageable)));
    }

    @PostMapping(path = "")
    @Secured(UserRole.Constants.ROLE_MANAGE)
    public ResponseEntity<Void> addActor(@RequestBody ActorDto.ActorRequest model) {
        final var result = actorService.addActor(model);
        return ResponseEntity.created(linkTo(methodOn(ActorController.class)
                .getActor(result.getActorId())).toUri()).build();
    }

    @GetMapping(path = "/{actorId}")
    @Secured(UserRole.Constants.ROLE_READ)
    public ResponseEntity<ActorDto.ActorResponse> getActor(@PathVariable Integer actorId) {
        return actorService.getActor(actorId)
                .map(actorAssembler::toModel)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @PutMapping(path = "/{actorId}")
    @Secured(UserRole.Constants.ROLE_MANAGE)
    public ResponseEntity<Void> updateActor(@PathVariable Integer actorId,
                                            @RequestBody ActorDto.ActorRequest model) {
        final var result = actorService.updateActor(actorId, model);
        return ResponseEntity.ok().build();
    }

    @DeleteMapping(path = "/{actorId}")
    @Secured(UserRole.Constants.ROLE_MANAGE)
    public ResponseEntity<Void> deleteActor(@PathVariable Integer actorId) {
        actorService.deleteActor(actorId);
        return ResponseEntity.noContent().build();
    }

    @GetMapping(path = "/{actorId}/details")
    @Secured(UserRole.Constants.ROLE_READ)
    public ResponseEntity<ActorDetailsDto.ActorDetailsResponse> getActorDetails(@PathVariable Integer actorId) {
        return actorService.getActorDetails(actorId)
                .map(actorDetailsAssembler::toModel)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @GetMapping(path = "/{actorId}/films")
    @Secured(UserRole.Constants.ROLE_READ)
    public ResponseEntity<CollectionModel<FilmDto.FilmResponse>> getActorFilmList(
            @PathVariable Integer actorId,
            @RequestParam(required = false) String category,
            @RequestParam(required = false) String releaseYear,
            @RequestParam(required = false) String rating,
            @PageableDefault(size = 10, page = 0, direction = Sort.Direction.ASC) Pageable pageable) {
        final var condition = FilmDto.FilterOption.builder()
                .category(category == null ? null : Category.CATEGORY_LOWER_MAP.get(category.toLowerCase()))
                .releaseYear(releaseYear == null ? null : Year.parse(releaseYear))
                .rating(rating == null ? null : FilmRating.valueOf(rating))
                .build();
        final var representation = filmAssembler.toCollectionModel(
                actorService.getActorFilmList(actorId, condition, pageable));
        final var updatedRepresentation = representation.removeLinks()
                .add(linkTo(methodOn(ActorController.class).getActorFilmList(actorId, category, releaseYear, rating, pageable))
                        .withSelfRel())
                .add(linkTo(methodOn(ActorController.class).getActor(actorId)).withRel(HalRelation.Fields.actor));
        return ResponseEntity.ok(updatedRepresentation);
    }

    @PostMapping(path = "/{actorId}/films")
    @Secured(UserRole.Constants.ROLE_MANAGE)
    public ResponseEntity<Void> addActorFilm(@PathVariable Integer actorId,
                                             @RequestBody Map<String, String> input) {
        final var result = actorService.addActorFilm(actorId, Integer.valueOf(input.get(FilmDto.Film.Fields.filmId)));
        return ResponseEntity.created(linkTo(methodOn(ActorController.class)
                .getActorFilm(actorId, result.getFilmId())).toUri()).build();
    }

    @GetMapping(path = "/{actorId}/films/{filmId}")
    @Secured(UserRole.Constants.ROLE_READ)
    public ResponseEntity<FilmDto.FilmResponse> getActorFilm(@PathVariable Integer actorId,
                                                             @PathVariable Integer filmId) {
        final var representation = actorService.getActorFilm(actorId, filmId)
                .map(filmAssembler::toModel);
        final var updatedRepresentation = representation.map(r -> r.removeLinks()
                .add(linkTo(methodOn(ActorController.class).getActorFilm(actorId, filmId)).withSelfRel())
                .add(linkTo(methodOn(ActorController.class).getActorFilmList(actorId, null, null, null, Pageable.unpaged()))
                        .withRel(HalRelation.Fields.filmList))
                .add(linkTo(methodOn(ActorController.class).getActor(actorId)).withRel(HalRelation.Fields.actor)));
        return updatedRepresentation.map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @DeleteMapping(path = "/{actorId}/films/{filmId}")
    @Secured(UserRole.Constants.ROLE_MANAGE)
    public ResponseEntity<Void> deleteActorFilm(@PathVariable Integer actorId,
                                                @PathVariable Integer filmId) {
        actorService.removeActorFilm(actorId, filmId);
        return ResponseEntity.noContent().build();
    }

    @GetMapping(path = "/{actorId}/films/{filmId}/details")
    @Secured(UserRole.Constants.ROLE_READ)
    public ResponseEntity<FilmDetailsDto.FilmDetailsResponse> getActorFilmDetails(@PathVariable Integer actorId,
                                                                                  @PathVariable Integer filmId) {
        final var representation = actorService.getActorFilmDetails(actorId, filmId)
                .map(filmDetailsAssembler::toModel);
        final var updatedRepresentation = representation.map(r -> r.removeLinks()
                .add(linkTo(methodOn(ActorController.class).getActorFilmDetails(actorId, filmId)).withSelfRel())
                .add(linkTo(methodOn(ActorController.class).getActorFilm(actorId, filmId)).withRel(HalRelation.Fields.film))
                .add(linkTo(methodOn(ActorController.class).getActorFilmList(actorId, null, null, null, Pageable.unpaged()))
                        .withRel(HalRelation.Fields.filmList))
                .add(linkTo(methodOn(ActorController.class).getActor(actorId)).withRel(HalRelation.Fields.actor)));
        return updatedRepresentation.map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @PostMapping(path = "/search")
    @Secured(UserRole.Constants.ROLE_READ)
    public ResponseEntity<CollectionModel<ActorDto.ActorResponse>> searchActorByName
            (@RequestBody Map<String, String> input) {
        return ResponseEntity.ok(actorAssembler.toCollectionModel(
                actorService.searchActorList(input.get("name"))));
    }
}
